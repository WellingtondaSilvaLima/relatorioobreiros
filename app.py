import os
import re
import smtplib
import json
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
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

st.set_page_config(
    page_title="Formulário Pastoral",  # Título que aparece na aba
    page_icon="assets/logo_igreja.png",  # Caminho para o favicon
    layout="centered",  # ou "wide" para layout expandido
    initial_sidebar_state="auto"  # ou "expanded", "collapsed"
)

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
    
    def delete_report(self, report_id: str) -> bool:
        """Exclui um relatório específico"""
        reports = self._load_reports()
        if report_id in reports:
            del reports[report_id]
            self._save_reports(reports)
            return True
        return False
    
    def delete_all_reports(self) -> int:
        """Exclui todos os relatórios e retorna o número excluído"""
        reports = self._load_reports()
        count = len(reports)
        if count > 0:
            self._save_reports({})
        return count
    
    def delete_reports_by_obreiro(self, obreiro_name: str) -> int:
        """Exclui todos os relatórios de um obreiro específico"""
        reports = self._load_reports()
        to_delete = [rid for rid, data in reports.items() 
                    if data.get("obreiro_name") == obreiro_name]
        
        for rid in to_delete:
            del reports[rid]
        
        if to_delete:
            self._save_reports(reports)
        
        return len(to_delete)
    
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
    
    def get_all_reports(self) -> List[Dict]:
        """Retorna todos os relatórios"""
        reports = self._load_reports()
        return [
            {**report_data, "id": report_id}
            for report_id, report_data in reports.items()
        ]
    
    def get_statistics(self) -> Dict:
        """Retorna estatísticas dos relatórios"""
        reports = self._load_reports()
        if not reports:
            return {
                "total": 0,
                "unique_obreiros": 0,
                "obreiros_list": [],
                "oldest_date": None,
                "newest_date": None
            }
        
        obreiros = set()
        dates = []
        
        for data in reports.values():
            obreiros.add(data.get("obreiro_name"))
            if "data_envio" in data:
                dates.append(datetime.fromisoformat(data["data_envio"]))
        
        return {
            "total": len(reports),
            "unique_obreiros": len(obreiros),
            "obreiros_list": sorted(list(obreiros)),
            "oldest_date": min(dates) if dates else None,
            "newest_date": max(dates) if dates else None
        }

def parse_allowed_users(raw: str) -> dict:
    """
    Formato no .env:
    ALLOWED_USERS=joao|123456|João da Silva|obreiro,maria|abc123|Maria Oliveira|pastor,ana|123456|Ana Souza|esposa_obreiro,carlos|123456|Carlos Silva|missionario,maria_s|123456|Maria Silva|missionaria
    
    Tipos de usuário:
    - obreiro: pode preencher e enviar formulários
    - esposa_obreiro: mesma permissão que obreiro
    - pastor: pode ver todos os relatórios e gerenciar dados
    - missionario: mesma permissão que pastor
    - missionaria: mesma permissão que pastor
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
        
        # Validar tipo de usuário
        valid_types = ["obreiro", "esposa_obreiro", "pastor", "missionario", "missionaria"]
        if user_type not in valid_types:
            # Se for inválido, define como obreiro por padrão
            user_type = "obreiro"
        
        users[username] = {
            "password": password,
            "name": full_name,
            "type": user_type
        }

    return users

def get_user_display_type(user_type: str) -> str:
    """Retorna o tipo de usuário para exibição na interface"""
    type_mapping = {
        "obreiro": "Obreiro",
        "esposa_obreiro": "Esposa de Obreiro",
        "pastor": "Pastor",
        "missionario": "Missionário",
        "missionaria": "Missionária"
    }
    return type_mapping.get(user_type, "Usuário")

def is_worker_type(user_type: str) -> bool:
    """Verifica se o tipo de usuário é de trabalhador (pode preencher formulário)"""
    worker_types = ["obreiro", "esposa_obreiro"]
    return user_type in worker_types

def is_leader_type(user_type: str) -> bool:
    """Verifica se o tipo de usuário é de líder (pode ver relatórios)"""
    leader_types = ["pastor", "missionario", "missionaria"]
    return user_type in leader_types

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
    timestamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M%S")
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
    data_text = f"Gerado em: {datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')}"
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
    if "show_delete_modal" not in st.session_state:
        st.session_state.show_delete_modal = False
    if "report_to_delete" not in st.session_state:
        st.session_state.report_to_delete = None

def logout():
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.full_name = ""
    st.session_state.user_type = ""
    st.session_state.show_delete_modal = False
    st.session_state.report_to_delete = None
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
# FORMULÁRIO (TRABALHADORES)
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
        st.write(f"**Tipo:** {get_user_display_type(st.session_state.user_type)}")
        st.button("Sair", on_click=logout)
        
        # Menu de navegação para líderes
        if is_leader_type(st.session_state.user_type):
            st.sidebar.subheader("Navegação")
            page = st.radio(
                "Selecione:",
                ["Ver Relatórios", "Gerenciar Dados"],
                label_visibility="collapsed"
            )
            return page

    if is_worker_type(st.session_state.user_type):
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
                    "user_type": st.session_state.user_type,  # Salvar o tipo de usuário
                    "data_envio": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
                    "form_data": form_data,
                    "pdf_name": pdf_name
                }
                
                # Salvar no arquivo JSON
                storage.save_report(report_id, report_data)

                st.success("Formulário enviado com sucesso e salvo no sistema!")
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
# GERENCIAMENTO DE DADOS (LÍDERES)
# =========================
def data_management_view():
    st.title("🗄️ Gerenciamento de Dados")
    st.caption(f"{get_user_display_type(st.session_state.user_type)}: {st.session_state.full_name}")
    
    # Estatísticas
    stats = storage.get_statistics()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Relatórios", stats["total"])
    with col2:
        st.metric("Pessoas que Enviaram", stats["unique_obreiros"])
    with col3:
        if stats["newest_date"]:
            st.metric("Último Envio", stats["newest_date"].strftime("%d/%m/%Y"))
    
    st.divider()
    
    # Opções de exclusão
    st.subheader("⚠️ Exclusão de Dados")
    
    tab1, tab2, tab3 = st.tabs(["Excluir por Pessoa", "Excluir Relatório Específico", "Excluir Todos"])
    
    with tab1:
        st.write("Excluir todos os relatórios de uma pessoa específica")
        
        if stats["obreiros_list"]:
            selected_obreiro = st.selectbox(
                "Selecione a pessoa:",
                stats["obreiros_list"],
                key="delete_by_obreiro"
            )
            
            # Mostrar quantos relatórios serão excluídos
            reports_to_delete = storage.get_reports_by_obreiro(selected_obreiro)
            if reports_to_delete:
                st.warning(f"⚠️ Serão excluídos {len(reports_to_delete)} relatório(s) de {selected_obreiro}")
                
                if st.button(f"🗑️ Excluir todos os relatórios de {selected_obreiro}", type="secondary"):
                    confirm = st.checkbox(f"Confirmar exclusão de {len(reports_to_delete)} relatório(s)?")
                    if confirm:
                        count = storage.delete_reports_by_obreiro(selected_obreiro)
                        st.success(f"✅ {count} relatório(s) excluído(s) com sucesso!")
                        st.rerun()
            else:
                st.info("Esta pessoa não possui relatórios")
        else:
            st.info("Nenhuma pessoa encontrada")
    
    with tab2:
        st.write("Excluir um relatório específico")
        
        all_reports = storage.get_all_reports()
        if all_reports:
            # Criar opções para seleção
            report_options = {}
            for report in all_reports:
                data_str = datetime.fromisoformat(report["data_envio"]).strftime("%d/%m/%Y %H:%M")
                user_type_display = get_user_display_type(report.get("user_type", "obreiro"))
                label = f"{report['obreiro_name']} ({user_type_display}) - {data_str}"
                report_options[label] = report["id"]
            
            selected_report_label = st.selectbox(
                "Selecione o relatório:",
                list(report_options.keys()),
                key="delete_specific_report"
            )
            
            selected_report_id = report_options[selected_report_label]
            
            if st.button("🗑️ Excluir este relatório", type="secondary"):
                confirm = st.checkbox("Confirmar exclusão deste relatório?")
                if confirm:
                    if storage.delete_report(selected_report_id):
                        st.success("✅ Relatório excluído com sucesso!")
                        st.rerun()
                    else:
                        st.error("Erro ao excluir relatório")
        else:
            st.info("Nenhum relatório encontrado")
    
    with tab3:
        st.write("⚠️ **ATENÇÃO:** Esta ação excluirá TODOS os relatórios do sistema!")
        
        if stats["total"] > 0:
            st.error(f"⚠️ Você está prestes a excluir {stats['total']} relatório(s) permanentemente!")
            
            # Confirmação em duas etapas
            confirm_text = st.text_input(
                "Digite 'EXCLUIR TUDO' para confirmar:",
                type="password",
                key="confirm_delete_all"
            )
            
            if confirm_text == "EXCLUIR TUDO":
                if st.button("🗑️ Excluir TODOS os relatórios", type="primary"):
                    count = storage.delete_all_reports()
                    st.success(f"✅ {count} relatório(s) excluído(s) com sucesso!")
                    st.rerun()
            else:
                if confirm_text:
                    st.warning("Confirmação incorreta. Digite 'EXCLUIR TUDO' para prosseguir.")
        else:
            st.info("Nenhum relatório para excluir")
    
    # Backup dos dados
    st.divider()
    st.subheader("💾 Backup dos Dados")
    
    col_backup1, col_backup2 = st.columns(2)
    
    with col_backup1:
        if stats["total"] > 0:
            # Botão para baixar backup
            reports_data = storage._load_reports()
            if reports_data:
                backup_json = json.dumps(reports_data, ensure_ascii=False, indent=2)
                st.download_button(
                    label="📥 Baixar Backup dos Dados",
                    data=backup_json,
                    file_name=f"backup_reports_{datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )
    
    with col_backup2:
        # Upload para restaurar backup
        uploaded_file = st.file_uploader(
            "Restaurar Backup",
            type=["json"],
            help="Selecione um arquivo JSON de backup para restaurar os dados"
        )
        
        if uploaded_file:
            try:
                backup_data = json.load(uploaded_file)
                st.warning(f"⚠️ Isso substituirá todos os {stats['total']} relatório(s) atuais por {len(backup_data)} do backup!")
                
                confirm_restore = st.checkbox("Confirmar restauração do backup?")
                if confirm_restore:
                    storage._save_reports(backup_data)
                    st.success("✅ Backup restaurado com sucesso!")
                    st.rerun()
            except json.JSONDecodeError:
                st.error("Arquivo inválido. Por favor, selecione um arquivo JSON válido.")

# =========================
# VISUALIZAÇÃO DE RELATÓRIOS (LÍDERES)
# =========================
def leader_view():
    col1, col2 = st.columns([1, 4])

    with col1:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=90)

    with col2:
        st.title("Relatórios Recebidos")
        st.caption(f"{get_user_display_type(st.session_state.user_type)}: {st.session_state.full_name}")

    # Menu na sidebar
    with st.sidebar:
        st.write(f"**Logado como:** {st.session_state.full_name}")
        st.write(f"**Tipo:** {get_user_display_type(st.session_state.user_type)}")
        st.button("Sair", on_click=logout)
        
        st.sidebar.subheader("Navegação")
        page = st.radio(
            "Selecione:",
            ["Ver Relatórios", "Gerenciar Dados"],
            label_visibility="collapsed"
        )
    
    if page == "Gerenciar Dados":
        data_management_view()
        return
    
    # Buscar todos os relatórios
    reports = storage.get_reports_by_pastor(st.session_state.full_name)
    
    if not reports:
        st.info("Nenhum relatório encontrado. As pessoas ainda não enviaram formulários.")
        return
    
    # Filtros
    col_filter1, col_filter2, col_filter3, col_filter4 = st.columns(4)
    with col_filter1:
        # Filtrar por pessoa
        pessoas = list(set([r["obreiro_name"] for r in reports]))
        selected_pessoa = st.selectbox("Filtrar por Pessoa:", ["Todos"] + pessoas)
    
    with col_filter2:
        # Filtrar por tipo de usuário
        user_types = list(set([r.get("user_type", "obreiro") for r in reports]))
        user_type_names = ["Todos"] + [get_user_display_type(ut) for ut in user_types]
        selected_type_name = st.selectbox("Filtrar por Tipo:", user_type_names)
        
        # Converter o nome exibido de volta para o tipo
        if selected_type_name != "Todos":
            # Mapeamento reverso
            reverse_mapping = {v: k for k, v in {
                "obreiro": "Obreiro",
                "esposa_obreiro": "Esposa de Obreiro",
                "pastor": "Pastor",
                "missionario": "Missionário",
                "missionaria": "Missionária"
            }.items()}
            selected_type = reverse_mapping.get(selected_type_name)
        else:
            selected_type = None
    
    with col_filter3:
        # Ordenar por data
        sort_order = st.selectbox("Ordenar por data:", ["Mais recentes primeiro", "Mais antigos primeiro"])
    
    with col_filter4:
        # Opção de seleção múltipla para exclusão em lote
        multi_delete = st.checkbox("Modo de exclusão múltipla")
    
    # Aplicar filtros
    filtered_reports = reports
    if selected_pessoa != "Todos":
        filtered_reports = [r for r in reports if r["obreiro_name"] == selected_pessoa]
    
    if selected_type:
        filtered_reports = [r for r in filtered_reports if r.get("user_type", "obreiro") == selected_type]
    
    # Ordenar
    reverse = sort_order == "Mais recentes primeiro"
    filtered_reports.sort(key=lambda x: x["data_envio"], reverse=reverse)
    
    # Exibir estatísticas
    st.subheader("📊 Estatísticas")
    col_stats1, col_stats2, col_stats3, col_stats4 = st.columns(4)
    with col_stats1:
        st.metric("Total de Relatórios", len(filtered_reports))
    with col_stats2:
        st.metric("Pessoas que Enviaram", len(set([r["obreiro_name"] for r in filtered_reports])))
    with col_stats3:
        tipos_unicos = len(set([r.get("user_type", "obreiro") for r in filtered_reports]))
        st.metric("Tipos de Usuários", tipos_unicos)
    with col_stats4:
        st.metric("Último Envio", 
                  datetime.fromisoformat(filtered_reports[0]["data_envio"]).strftime("%d/%m/%Y %H:%M") 
                  if filtered_reports else "Nenhum")
    
    st.divider()
    
    # Modo de exclusão múltipla
    if multi_delete:
        st.warning("⚠️ Modo de exclusão múltipla ativado. Selecione os relatórios que deseja excluir.")
        selected_reports = []
        
        # Checkbox para selecionar todos
        select_all = st.checkbox("Selecionar todos os relatórios")
        
        for report in filtered_reports:
            col_check, col_expander = st.columns([0.1, 0.9])
            with col_check:
                if select_all:
                    selected = st.checkbox("", value=True, key=f"select_{report['id']}")
                else:
                    selected = st.checkbox("", key=f"select_{report['id']}")
                
                if selected:
                    selected_reports.append(report["id"])
            
            with col_expander:
                user_type_display = get_user_display_type(report.get("user_type", "obreiro"))
                with st.expander(f"📄 {report['obreiro_name']} ({user_type_display}) - {datetime.fromisoformat(report['data_envio']).strftime('%d/%m/%Y %H:%M')}"):
                    # Exibir dados do formulário
                    form_data = report["form_data"]
                    
                    st.markdown("**Dados do Relatório:**")
                    st.write(f"**Nome:** {form_data['nome']}")
                    st.write(f"**Tipo:** {user_type_display}")
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
        
        # Botão para excluir selecionados
        if selected_reports:
            st.warning(f"⚠️ {len(selected_reports)} relatório(s) selecionado(s) para exclusão")
            if st.button(f"🗑️ Excluir {len(selected_reports)} relatório(s) selecionado(s)", type="primary"):
                confirm = st.checkbox("Confirmar exclusão dos relatórios selecionados?")
                if confirm:
                    success_count = 0
                    for report_id in selected_reports:
                        if storage.delete_report(report_id):
                            success_count += 1
                    st.success(f"✅ {success_count} relatório(s) excluído(s) com sucesso!")
                    st.rerun()
    else:
        # Modo normal - exibir relatórios
        for report in filtered_reports:
            user_type_display = get_user_display_type(report.get("user_type", "obreiro"))
            with st.expander(f"📄 {report['obreiro_name']} ({user_type_display}) - {datetime.fromisoformat(report['data_envio']).strftime('%d/%m/%Y %H:%M')}"):
                # Exibir dados do formulário
                form_data = report["form_data"]
                
                # Botão de excluir individual
                col1, col2 = st.columns([0.9, 0.1])
                with col2:
                    if st.button("🗑️", key=f"delete_btn_{report['id']}", help="Excluir este relatório"):
                        st.session_state.show_delete_modal = True
                        st.session_state.report_to_delete = report["id"]
                        st.rerun()
                
                with col1:
                    st.markdown("**Dados do Relatório:**")
                
                st.write(f"**Nome:** {form_data['nome']}")
                st.write(f"**Tipo:** {user_type_display}")
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
        
        # Modal de confirmação de exclusão
        if st.session_state.show_delete_modal and st.session_state.report_to_delete:
            with st.expander("⚠️ Confirmar exclusão", expanded=True):
                st.warning("Tem certeza que deseja excluir este relatório? Esta ação não pode ser desfeita.")
                col_confirm1, col_confirm2 = st.columns(2)
                with col_confirm1:
                    if st.button("✅ Sim, excluir"):
                        if storage.delete_report(st.session_state.report_to_delete):
                            st.success("Relatório excluído com sucesso!")
                            st.session_state.show_delete_modal = False
                            st.session_state.report_to_delete = None
                            st.rerun()
                with col_confirm2:
                    if st.button("❌ Cancelar"):
                        st.session_state.show_delete_modal = False
                        st.session_state.report_to_delete = None
                        st.rerun()

# =========================
# APP
# =========================
def main():
    if not ALLOWED_USERS:
        st.error("Nenhum usuário autorizado foi configurado no .env.")
        st.stop()

    if st.session_state.authenticated:
        # Verificar tipo de usuário
        if is_leader_type(st.session_state.user_type):
            leader_view()
        elif is_worker_type(st.session_state.user_type):
            form_screen()
        else:
            st.error("Tipo de usuário inválido.")
            logout()
    else:
        login_screen()

if __name__ == "__main__":
    main()
