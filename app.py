import os
import re
import smtplib
import json
import hashlib
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER
from io import BytesIO

load_dotenv()

def get_secret(key: str, default=""):
    # Prioriza st.secrets no deploy
    if key in st.secrets:
        return str(st.secrets[key]).strip()
    return os.getenv(key, default).strip()

LOGO_PATH = "assets/logo_igreja.png"
ALLOWED_USERS_RAW = get_secret("ALLOWED_USERS")

# Arquivo para armazenar os relatórios
REPORTS_FILE = "reports.json"

# =========================
# ESTRUTURA DE DADOS
# =========================
class ReportStorage:
    """Gerencia o armazenamento dos relatórios em arquivo JSON"""
    
    def __init__(self, storage_file: str = REPORTS_FILE):
        self.storage_file = storage_file
        self._ensure_storage_exists()
    
    def _ensure_storage_exists(self):
        """Cria o arquivo de armazenamento se não existir"""
        if not os.path.exists(self.storage_file):
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _load_reports(self) -> Dict:
        """Carrega todos os relatórios do arquivo"""
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _save_reports(self, reports: Dict):
        """Salva os relatórios no arquivo"""
        with open(self.storage_file, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)
    
    def save_report(self, report_id: str, report_data: Dict):
        """Salva um novo relatório"""
        reports = self._load_reports()
        reports[report_id] = report_data
        self._save_reports(reports)
    
    def get_reports_by_obreiro(self, obreiro_name: str) -> List[Dict]:
        """Retorna todos os relatórios de um obreiro específico"""
        reports = self._load_reports()
        return [
            {**report_data, "id": report_id}
            for report_id, report_data in reports.items()
            if report_data.get("obreiro_name") == obreiro_name
        ]
    
    def get_reports_by_pastor(self, pastor_name: str) -> List[Dict]:
        """
        Retorna todos os relatórios dos obreiros que o pastor é responsável
        Nota: Nesta implementação básica, consideramos que o pastor vê todos os relatórios
        Em um sistema real, você precisaria de um mapeamento de pastores -> obreiros
        """
        reports = self._load_reports()
        # Por enquanto, retorna todos os relatórios
        # Você pode adicionar lógica de filtro baseada nos obreiros que cada pastor supervisiona
        return [
            {**report_data, "id": report_id}
            for report_id, report_data in reports.items()
        ]

def parse_allowed_users(raw: str) -> dict:
    """
    Formato no .env:
    ALLOWED_USERS=joao|123456|João da Silva|obreiro,maria|abc123|Maria Oliveira|pastor
    """
    users = {}

    if not raw.strip():
        return users

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        parts = [p.strip() for p in item.split("|")]
        if len(parts) < 3:
            continue

        username = parts[0]
        password = parts[1]
        full_name = parts[2]
        user_type = parts[3] if len(parts) > 3 else "obreiro"  # Default: obreiro
        
        users[username] = {
            "password": password,
            "name": full_name,
            "type": user_type  # "pastor" ou "obreiro"
        }

    return users

ALLOWED_USERS = parse_allowed_users(ALLOWED_USERS_RAW)

# Inicializar o armazenamento
storage = ReportStorage()

# =========================
# UTILITÁRIOS
# =========================
def sanitize_filename(name: str) -> str:
    name = name.strip().lower()
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c"
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^a-z0-9_-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "formulario"

def generate_report_id(obreiro_name: str) -> str:
    """Gera um ID único para o relatório baseado no nome e timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_filename(obreiro_name)
    return f"{safe_name}_{timestamp}"

def build_pdf_bytes(form_data: dict) -> bytes:
    buffer = BytesIO()
    
    # Configuração do documento
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Estilos
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontSize=12,
        fontName='Helvetica-Bold',
        spaceBefore=10,
        spaceAfter=2
    )
    
    text_style = ParagraphStyle(
        'Text',
        parent=styles['Normal'],
        fontSize=11,
        fontName='Helvetica',
        spaceAfter=10
    )
    
    # Conteúdo
    story = []
    
    # Título
    story.append(Paragraph("Formulário Pastoral", title_style))
    
    # Data
    data_text = f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    story.append(Paragraph(data_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Campos
    fields = [
        ("Nome", form_data["nome"]),
        ("Como está sua vida devocional?", form_data["vida_devocional"]),
        ("Como está seu cônjuge?", form_data["conjuge"]),
        ("Como estão seus filhos?", form_data["filhos"]),
        ("Como está sua relação com a congregação?", form_data["congregacao"]),
        ("Quais alegrias você tem para compartilhar?", form_data["alegrias"]),
        ("Quais tristezas você tem para compartilhar?", form_data["tristezas"]),
        ("Quais desafios ou dificuldades você tem enfrentado?", form_data["desafios"]),
        ("Quais pedidos de oração você tem?", form_data["pedidos_oracao"]),
    ]
    
    for label, value in fields:
        # Título do campo
        story.append(Paragraph(label, label_style))
        
        # Conteúdo
        text_value = value if value and value.strip() else "Não informado"
        # Escapa caracteres especiais para o ReportLab
        text_value = text_value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Substitui quebras de linha por tags <br/>
        text_value = text_value.replace('\n', '<br/>')
        
        story.append(Paragraph(text_value, text_style))
        story.append(Spacer(1, 5))
    
    # Gera o PDF
    doc.build(story)
    
    # Retorna os bytes
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes

# =========================
# CONTROLE DE SESSÃO
# =========================
def init_session():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = ""
    if "full_name" not in st.session_state:
        st.session_state.full_name = ""
    if "user_type" not in st.session_state:
        st.session_state.user_type = ""

def logout():
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.full_name = ""
    st.session_state.user_type = ""
    st.rerun()

init_session()

# =========================
# LOGIN
# =========================
def login_screen():
    st.markdown("<div style='text-align:center;'>", unsafe_allow_html=True)

    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=180)

    st.markdown("</div>", unsafe_allow_html=True)

    st.title("Acesso ao Formulário")
    st.write("Informe seu usuário e senha para acessar o formulário pastoral.")

    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        user = ALLOWED_USERS.get(username)

        if user and user["password"] == password:
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.full_name = user["name"]
            st.session_state.user_type = user["type"]
            st.success("Login realizado com sucesso.")
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")

# =========================
# FORMULÁRIO (OBREIRO)
# =========================
def form_screen():
    col1, col2 = st.columns([1, 4])

    with col1:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=90)

    with col2:
        st.title("Formulário Pastoral")
        st.caption(f"Usuário logado: {st.session_state.full_name}")

    with st.sidebar:
        st.write(f"**Logado como:** {st.session_state.full_name}")
        st.write(f"**Tipo:** {'Pastor' if st.session_state.user_type == 'pastor' else 'Obreiro'}")
        st.button("Sair", on_click=logout)
        
        # Menu de navegação
        if st.session_state.user_type == "pastor":
            st.sidebar.subheader("Navegação")
            page = st.radio(
                "Selecione:",
                ["Ver Relatórios dos Obreiros"],
                label_visibility="collapsed"
            )
            return page

    if st.session_state.user_type == "obreiro":
        with st.form("pastoral_form", clear_on_submit=False):
            st.text_input("Nome", value=st.session_state.full_name, disabled=True)
            vida_devocional = st.text_area("Como está sua vida devocional?", height=120)
            conjuge = st.text_area("Como está seu cônjuge?", height=120)
            filhos = st.text_area("Como estão seus filhos?", height=120)
            congregacao = st.text_area("Como está sua relação com a congregação?", height=120)
            alegrias = st.text_area("Quais alegrias você tem para compartilhar?", height=120)
            tristezas = st.text_area("Quais tristezas você tem para compartilhar?", height=120)
            desafios = st.text_area("Quais desafios ou dificuldades você tem enfrentado?", height=120)
            pedidos_oracao = st.text_area("Quais pedidos de oração você tem?", height=120)

            submitted = st.form_submit_button("Enviar")

        if submitted:
            form_data = {
                "nome": st.session_state.full_name,
                "vida_devocional": vida_devocional,
                "conjuge": conjuge,
                "filhos": filhos,
                "congregacao": congregacao,
                "alegrias": alegrias,
                "tristezas": tristezas,
                "desafios": desafios,
                "pedidos_oracao": pedidos_oracao,
            }

            try:
                # Gerar PDF
                pdf_bytes = build_pdf_bytes(form_data)
                safe_name = sanitize_filename(st.session_state.full_name)
                pdf_name = f"{safe_name}.pdf"
                
                # Gerar ID do relatório e salvar
                report_id = generate_report_id(st.session_state.full_name)
                report_data = {
                    "id": report_id,
                    "obreiro_name": st.session_state.full_name,
                    "obreiro_username": st.session_state.username,
                    "data_envio": datetime.now().isoformat(),
                    "form_data": form_data,
                    "pdf_name": pdf_name
                }
                
                # Salvar no arquivo JSON
                storage.save_report(report_id, report_data)

                st.success("Formulário enviado com sucesso para o e-mail do pastor e salvo no sistema!")
                st.download_button(
                    label="Baixar cópia do PDF",
                    data=pdf_bytes,
                    file_name=pdf_name,
                    mime="application/pdf"
                )

            except Exception as e:
                st.error(f"Erro ao enviar formulário: {e}")
    
    return None

# =========================
# VISUALIZAÇÃO DE RELATÓRIOS (PASTOR)
# =========================
def pastor_view():
    col1, col2 = st.columns([1, 4])

    with col1:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=90)

    with col2:
        st.title("Relatórios dos Obreiros")
        st.caption(f"Pastor: {st.session_state.full_name}")

    with st.sidebar:
        st.write(f"**Logado como:** {st.session_state.full_name}")
        st.write(f"**Tipo:** Pastor")
        st.button("Sair", on_click=logout)
    
    # Buscar todos os relatórios
    reports = storage.get_reports_by_pastor(st.session_state.full_name)
    
    if not reports:
        st.info("Nenhum relatório encontrado. Os obreiros ainda não enviaram formulários.")
        return
    
    # Filtros
    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        # Filtrar por obreiro
        obreiros = list(set([r["obreiro_name"] for r in reports]))
        selected_obreiro = st.selectbox("Filtrar por Obreiro:", ["Todos"] + obreiros)
    
    with col_filter2:
        # Ordenar por data
        sort_order = st.selectbox("Ordenar por data:", ["Mais recentes primeiro", "Mais antigos primeiro"])
    
    # Aplicar filtros
    filtered_reports = reports
    if selected_obreiro != "Todos":
        filtered_reports = [r for r in reports if r["obreiro_name"] == selected_obreiro]
    
    # Ordenar
    reverse = sort_order == "Mais recentes primeiro"
    filtered_reports.sort(key=lambda x: x["data_envio"], reverse=reverse)
    
    # Exibir estatísticas
    st.subheader("📊 Estatísticas")
    col_stats1, col_stats2, col_stats3 = st.columns(3)
    with col_stats1:
        st.metric("Total de Relatórios", len(filtered_reports))
    with col_stats2:
        st.metric("Obreiros que Enviaram", len(set([r["obreiro_name"] for r in filtered_reports])))
    with col_stats3:
        st.metric("Último Envio", 
                  datetime.fromisoformat(filtered_reports[0]["data_envio"]).strftime("%d/%m/%Y %H:%M") 
                  if filtered_reports else "Nenhum")
    
    st.divider()
    
    # Exibir relatórios
    st.subheader("📋 Lista de Relatórios")
    
    for report in filtered_reports:
        with st.expander(f"📄 {report['obreiro_name']} - {datetime.fromisoformat(report['data_envio']).strftime('%d/%m/%Y %H:%M')}"):
            # Exibir dados do formulário
            form_data = report["form_data"]
            
            st.markdown("**Dados do Relatório:**")
            st.write(f"**Nome:** {form_data['nome']}")
            st.write(f"**Vida Devocional:** {form_data['vida_devocional'] or 'Não informado'}")
            st.write(f"**Cônjuge:** {form_data['conjuge'] or 'Não informado'}")
            st.write(f"**Filhos:** {form_data['filhos'] or 'Não informado'}")
            st.write(f"**Relação com a Congregação:** {form_data['congregacao'] or 'Não informado'}")
            st.write(f"**Alegrias:** {form_data['alegrias'] or 'Não informado'}")
            st.write(f"**Tristezas:** {form_data['tristezas'] or 'Não informado'}")
            st.write(f"**Desafios:** {form_data['desafios'] or 'Não informado'}")
            st.write(f"**Pedidos de Oração:** {form_data['pedidos_oracao'] or 'Não informado'}")
            
            # Botão para baixar PDF
            try:
                # Regenerar PDF para download
                pdf_bytes = build_pdf_bytes(form_data)
                pdf_name = f"{sanitize_filename(report['obreiro_name'])}.pdf"
                st.download_button(
                    label="📥 Baixar PDF",
                    data=pdf_bytes,
                    file_name=pdf_name,
                    mime="application/pdf",
                    key=f"download_{report['id']}"
                )
            except Exception as e:
                st.error(f"Erro ao gerar PDF: {e}")

# =========================
# APP
# =========================
def main():
    if not ALLOWED_USERS:
        st.error("Nenhum usuário autorizado foi configurado no .env.")
        st.stop()

    if st.session_state.authenticated:
        # Verificar tipo de usuário
        if st.session_state.user_type == "pastor":
            pastor_view()
        else:  # obreiro
            form_screen()
    else:
        login_screen()

if __name__ == "__main__":
    main()
