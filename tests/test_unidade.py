from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flask import Flask
from app import db
from app.painel_events import PainelEvents
from app.routes import bp


class UnidadeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        templates = Path(__file__).resolve().parents[1] / "app" / "templates"
        self.app = Flask(__name__, template_folder=str(templates))
        self.app.config.update(TESTING=True, SECRET_KEY="test",
                               DEFAULT_UNIDADE="UNIDADE",
                               DB_PATH=str(Path(self.directory.name) / "test.db"))
        self.app.extensions["painel_events"] = PainelEvents()
        self.app.register_blueprint(bp)
        with self.app.app_context():
            db.init_db()
        self.client = self.app.test_client()

    def test_emission_uses_default_and_saved_unit_name(self):
        self.assertNotIn('name="unidade"', self.client.get("/gerar").get_data(as_text=True))
        normal = self.client.post("/senhas/emitir/normal")
        self.assertEqual(normal.get_json()["senha"], "101")
        with self.app.app_context():
            db.salvar_unidade_padrao("Nova Unidade")
        preferencial = self.client.post("/senhas/emitir/preferencial")
        self.assertEqual(preferencial.get_json()["senha"], "001")
        with self.app.app_context(), db.conectar() as conn:
            rows = conn.execute("SELECT unidade FROM senha ORDER BY id").fetchall()
            self.assertEqual([row["unidade"] for row in rows], ["ULSAV SMG", "Nova Unidade"])

    def test_wake_lock_is_loaded_only_on_ticket_emission_page(self):
        response = self.client.get("/senhas")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('src="/static/js/senhas-wake-lock.js" defer', page)
        self.assertIn('id="wake-lock-notice" role="status" hidden', page)
        self.assertIn('data-issue-url="/senhas/emitir/normal"', page)
        self.assertIn('data-issue-url="/senhas/emitir/preferencial"', page)
        for route in ("/", "/gerar", "/painel", "/chamar"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("senhas-wake-lock.js", response.get_data(as_text=True))

    def test_blank_save_keeps_name_and_batch_uses_saved_default(self):
        with self.app.app_context():
            db.salvar_unidade_padrao("Unidade Salva")
        self.client.post("/gerar", data={"senha_inicial": "1", "senha_final": "1", "data_execucao": "2026-11-04"})
        with self.app.app_context(), db.conectar() as conn:
            self.assertEqual(db.obter_unidade_padrao(), "Unidade Salva")
            self.assertEqual(conn.execute("SELECT unidade FROM senha").fetchone()["unidade"], "Unidade Salva")
