import streamlit as st 
import os
from typing import Optional


def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == os.environ.get("PASSWORD"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True


def remove_default_index_col():
    # CSS to inject contained in a string
    hide_table_row_index = """
                <style>
                tbody th {display:none}
                .blank {display:none}
                </style>
                """

    # Inject CSS with Markdown
    st.markdown(hide_table_row_index, unsafe_allow_html=True)


def get_tx_explorer_url(tx_hash: str, chain_id: int) -> str:
    explorers = {
        1: "https://etherscan.io/",
        4: "https://rinkeby.etherscan.io/",
        137: "https://polygonscan.com/",
        80001: "https://mumbai.polygonscan.com/",
    }
    base_url = explorers[chain_id]
    return f"{base_url}tx/{tx_hash}"


def disputable_str(disputable: Optional[bool], query_id: str) -> str:
    if disputable is not None:
        return "yes ❗📲" if disputable else "no ✔️"
    return f"❗unsupported query ID: {query_id}"
