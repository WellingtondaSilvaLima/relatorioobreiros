import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage

import streamlit as st
from dotenv import load_dotenv
from fpdf import FPDF

# =========================
# CONFIGURAÇÕES INICIAIS
# =========================
load_dotenv()

st.set_page_config(
    page_title="Formulário Pastoral",
    page_icon="assets/logo_igreja.png",
    layout="centered"
)

LOGO_PATH = "assets/logo_igreja.png"
PASTOR_EMAIL = os.getenv("PASTOR_EMAIL", "")
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")


def parse_allowed_users(raw: str) -> dict:
    """
    Formato no .env:
    ALLOWED_USERS=joao|123456|João da Silva,maria|abc123|Maria Oliveira
    """
    users = {}

    if not raw.strip():
        return users

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        parts = [p.strip() for p in item.split("|")]
        if len(parts) != 3:
            continue

        username, password, full_name = parts
        users[username] = {
            "password": password,
            "name": full_name
        }

    return users


ALLOWED_USERS = parse_allowed_users(ALLOWED_USERS_RAW)


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


class PDFWithUTF8(FPDF):
    def __init__(self):
        super().__init__()
        # Adiciona suporte a Unicode
        self.set_font("helvetica", size=11)


def build_pdf_bytes(form_data: dict) -> bytes:
    pdf = PDFWithUTF8()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    
    # Título
    pdf.set_font("helvetica", style="B", size=16)
    pdf.multi_cell(0, 10, "Formulário Pastoral")
    pdf.ln(2)

    # Data de geração
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.ln(4)

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
        # Título do campo em negrito
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 8, label)
        
        # Conteúdo do campo
        pdf.set_font("Helvetica", "", 11)
        text_value = value if value and value.strip() else "Não informado"
        
        # Quebra o texto em linhas para garantir que não ultrapasse a largura
        lines = text_value.split('\n')
        for line in lines:
            if line.strip():
                # Usa multi_cell para garantir quebra automática de linha
                pdf.multi_cell(0, 7, line.strip())
            else:
                pdf.multi_cell(0, 7, " ")
        
        pdf.ln(2)  # Espaço entre campos

    return bytes(pdf.output(dest="S"))


def send_email_with_pdf(pdf_bytes: bytes, recipient_email: str, file_name: str, logged_user_name: str):
    if not SMTP_EMAIL or not SMTP_PASSWORD or not recipient_email:
        raise ValueError("Credenciais de e-mail ou destinatário não configurados.")

    msg = EmailMessage()
    msg["Subject"] = f"Formulário Pastoral - {logged_user_name}"
    msg["From"] = SMTP_EMAIL
    msg["To"] = recipient_email
    msg.set_content(
        f"Olá,\n\nSegue em anexo o formulário pastoral preenchido por {logged_user_name}.\n\n"
        f"Enviado automaticamente pelo sistema."
    )

    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=file_name
    )

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)


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


def logout():
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.full_name = ""
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
            st.success("Login realizado com sucesso.")
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")


# =========================
# FORMULÁRIO
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
        st.button("Sair", on_click=logout)

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
            pdf_bytes = build_pdf_bytes(form_data)
            safe_name = sanitize_filename(st.session_state.full_name)
            pdf_name = f"{safe_name}.pdf"

            send_email_with_pdf(
                pdf_bytes=pdf_bytes,
                recipient_email=PASTOR_EMAIL,
                file_name=pdf_name,
                logged_user_name=st.session_state.full_name
            )

            st.success("Formulário enviado com sucesso para o e-mail do pastor.")
            st.download_button(
                label="Baixar cópia do PDF",
                data=pdf_bytes,
                file_name=pdf_name,
                mime="application/pdf"
            )

        except Exception as e:
            st.error(f"Erro ao enviar formulário: {e}")


# =========================
# APP
# =========================
def main():
    if not ALLOWED_USERS:
        st.error("Nenhum usuário autorizado foi configurado no .env.")
        st.stop()

    if st.session_state.authenticated:
        form_screen()
    else:
        login_screen()


if __name__ == "__main__":
    main()