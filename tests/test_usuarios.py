"""Testes de usuários, senhas e permissões."""
from core import usuarios as u

from .test_importacao import BaseBanco

SENHA = "Financeiro2026"


class TestSenhas(BaseBanco):
    def test_hash_nao_guarda_senha_e_confere(self):
        h = u.gerar_hash(SENHA)
        self.assertNotIn(SENHA, h)
        self.assertTrue(u.conferir_senha(SENHA, h))
        self.assertFalse(u.conferir_senha("Financeiro2027", h))
        self.assertNotEqual(h, u.gerar_hash(SENHA))  # sal diferente a cada vez
        self.assertFalse(u.conferir_senha(SENHA, "lixo"))

    def test_regras_de_senha(self):
        self.assertTrue(u.validar_senha("curta1"))
        self.assertTrue(u.validar_senha("somenteletras"))
        self.assertTrue(u.validar_senha("maria2026x", "maria"))
        self.assertFalse(u.validar_senha(SENHA, "maria"))
        self.assertFalse(u.validar_senha(u.gerar_senha_temporaria()))


class TestUsuarios(BaseBanco):
    def setUp(self):
        super().setUp()
        self.admin = u.criar_primeiro_administrador(self.con, "Admin.Fin", "Administradora", SENHA)

    def test_primeiro_admin_so_uma_vez(self):
        self.assertEqual((self.admin.login, self.admin.perfil, self.admin.trocar_senha), ("admin.fin", "administrador", False))
        with self.assertRaises(u.ErroUsuario):
            u.criar_primeiro_administrador(self.con, "outro", "Outro", SENHA)

    def test_login(self):
        self.assertTrue(u.autenticar(self.con, "ADMIN.FIN ", SENHA).ok)
        r = u.autenticar(self.con, "admin.fin", "errada123")
        self.assertFalse(r.ok)
        self.assertEqual(r.mensagem, u.autenticar(self.con, "naoexiste", SENHA).mensagem)  # não revela

    def test_bloqueio_apos_tentativas(self):
        for _ in range(u.MAX_TENTATIVAS):
            r = u.autenticar(self.con, "admin.fin", "errada123")
        self.assertIn("bloqueado", r.mensagem)
        self.assertFalse(u.autenticar(self.con, "admin.fin", SENHA).ok)  # nem com a senha certa
        self.con.execute("UPDATE usuarios SET bloqueado_ate = '2000-01-01T00:00:00'")
        self.assertTrue(u.autenticar(self.con, "admin.fin", SENHA).ok)

    def test_novo_usuario_troca_senha_no_primeiro_acesso(self):
        op = u.criar(self.con, "joana", "Joana", "operador", "Temporaria1", "admin.fin")
        self.assertTrue(op.trocar_senha)
        with self.assertRaises(u.ErroUsuario):
            u.trocar_senha(self.con, "joana", "Temporaria1", "Temporaria1")
        u.trocar_senha(self.con, "joana", "Temporaria1", "NovaSenha99")
        self.assertFalse(u.buscar(self.con, "joana").trocar_senha)
        self.assertTrue(u.autenticar(self.con, "joana", "NovaSenha99").ok)

    def test_desativado_nao_entra_e_redefinir(self):
        u.criar(self.con, "diretor", "Diretor", "consulta", "Temporaria1", "admin.fin")
        u.alterar(self.con, "diretor", "admin.fin", ativo=False)
        self.assertIn("desativado", u.autenticar(self.con, "diretor", "Temporaria1").mensagem)
        u.alterar(self.con, "diretor", "admin.fin", ativo=True)
        temp = u.redefinir_senha(self.con, "diretor", "admin.fin")
        self.assertTrue(u.autenticar(self.con, "diretor", temp).ok)
        self.assertTrue(u.buscar(self.con, "diretor").trocar_senha)

    def test_sempre_um_administrador(self):
        with self.assertRaises(u.ErroUsuario):
            u.alterar(self.con, "admin.fin", "admin.fin", perfil="operador")
        with self.assertRaises(u.ErroUsuario):
            u.alterar(self.con, "admin.fin", "outro", ativo=False)
        u.criar(self.con, "admin2", "Admin 2", "administrador", "Temporaria1", "admin.fin")
        u.alterar(self.con, "admin.fin", "admin2", perfil="operador")
        with self.assertRaises(u.ErroUsuario):
            u.alterar(self.con, "admin2", "admin2", ativo=False)  # não desativa a si mesmo

    def test_login_duplicado_e_invalido(self):
        with self.assertRaises(u.ErroUsuario):
            u.criar(self.con, "admin.fin", "X", "operador", "Temporaria1", "admin.fin")
        with self.assertRaises(u.ErroUsuario):
            u.criar(self.con, "joão", "X", "operador", "Temporaria1", "admin.fin")

    def test_auditoria(self):
        u.autenticar(self.con, "admin.fin", SENHA)
        u.autenticar(self.con, "admin.fin", "errada123")
        acoes = [r[0] for r in self.con.execute("SELECT acao FROM auditoria WHERE acao <> 'atualizacao_regras' ORDER BY id")]
        self.assertEqual(acoes, ["usuario_criado", "login", "login_falhou"])
        self.assertNotIn(SENHA, str(list(self.con.execute("SELECT * FROM auditoria"))))


class TestPermissoes(BaseBanco):
    def test_perfis(self):
        self.assertTrue(u.pode("administrador", "excluir_importacao"))
        self.assertFalse(u.pode("operador", "excluir_importacao"))
        self.assertTrue(u.pode("operador", "importar"))
        self.assertTrue(u.pode("operador", "resolver_conflito"))
        self.assertFalse(u.pode("consulta", "importar"))
        self.assertTrue(u.pode("consulta", "exportar"))
        self.assertFalse(u.pode_ver("consulta", "Importações"))
        self.assertFalse(u.pode_ver("consulta", "Configurações"))
        self.assertTrue(u.pode_ver("consulta", "Dashboard"))
        self.assertFalse(u.pode(None, "exportar"))
