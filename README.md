# Receita Colégio Notarial do Brasil

Sistema web em **Python + Streamlit** para importar as planilhas da intermediadora de pagamentos,
classificar as receitas, conferir os valores e gerar relatórios, substituindo o controle manual em Excel.

> **Repositório de amostra.** Todos os dados aqui são **fictícios**. A planilha
> `dados/amostra_ficticia.xlsx` tem a mesma estrutura da planilha real (colunas, linhas de split,
> rodapé com totais, formatos de data), mas nomes, documentos, identificadores e valores foram
> gerados por `scripts/gerar_amostra_ficticia.py`. Nenhum dado real de pagamento está publicado.

## O que o sistema faz

- **Importação** de .xlsx com prévia antes de gravar, validação de valores e datas, detecção de
  duplicidades e conflitos (reimportar não duplica nada) e histórico com exclusão segura.
- **Classificação** por prefixo do Nº do Pedido, com regras editáveis e classificação manual.
- **Dashboard**, **Receita Diária** e **Boletos Processados**, com filtros combináveis e gráficos Plotly.
- **Conciliação**: 11 verificações (Líquido = Bruto − Custo, datas, status, duplicidades...),
  conferência da composição dos totais e decisão sobre conflitos.
- **Relatórios** em Excel e CSV no padrão brasileiro (R$ 1.234,56, DD/MM/AAAA).
- **Login com perfis** (Administrador, Operador, Consulta), senhas com scrypt, bloqueio por
  tentativas, sessão com expiração e auditoria completa.
- **Banco SQLite** com backup diário, verificação de integridade e tela de recuperação; funciona
  no computador, em pasta de rede compartilhada ou como serviço num servidor.
- **71 testes automáticos** (`unittest`).

## Rodar a demonstração

```
python -m venv .venv
.venv\Scripts\activate            (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

1. Na primeira tela, crie o usuário administrador.
2. Em **Importações**, envie `dados/amostra_ficticia.xlsx` e confirme com a data 09/11/2026.
3. Veja o Dashboard, a Conciliação e os Relatórios.

Testes: `python -m unittest discover -s tests -t . -v`


## Notas técnicas

(Nome anterior: Cloud Finance. A pasta `cloud_finance`, o banco `dados/cloud_finance.db` e as variáveis `CLOUD_FINANCE_*` mantêm o nome técnico antigo para não afetar os dados já gravados. O nome exibido fica em `core/marca.py`.)

Sistema de controle, análise e conciliação de receitas (CENSEC / e-Not).

## Implantação na pasta de rede (Z:)

O programa e os dados ficam em `Z:\ReceitaCNB`, e cada pessoa abre o sistema no próprio
computador pelo atalho "Receita CNB". Passo a passo em **IMPLANTACAO.md** (seção A):
`deploy\pasta_rede\Montar pasta do sistema.bat` monta ou atualiza a pasta, e
`Instalar neste computador.bat` prepara cada computador. O guia também traz alternativas
de servidor (IIS, nginx, Docker).

## Rodar no computador (Windows)

1. Instale o Python 3.11 ou mais recente (python.org — marque "Add Python to PATH").
2. Abra o Prompt de Comando na pasta `cloud_finance` e rode, uma única vez:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Para abrir o sistema (sempre que for usar):
   ```
   .venv\Scripts\activate
   streamlit run app.py
   ```
   O navegador abre em http://localhost:8501.

Os dados ficam em `dados/cloud_finance.db` (banco SQLite). Faça cópias dessa
pasta ou use a função de backup (`core/banco.py: fazer_backup`).

## Acesso e usuários

- **Primeiro acesso:** na primeira vez que o sistema abre sem usuários, ele pede para criar o
  **administrador**. Não existe usuário nem senha padrão no código.
- O administrador cadastra os demais em **Configurações → Usuários**. O sistema gera uma senha
  temporária, e a pessoa cria a própria senha no primeiro acesso.
- Perfis:

| Perfil | Pode |
|---|---|
| Administrador | Tudo, inclusive usuários, regras, receitas, exclusão de importações, backup e auditoria |
| Operador | Importar, classificar manualmente, resolver conflitos, ver tudo e exportar |
| Consulta | Dashboard, Receita Diária, Boletos, Transações, Conciliação e Relatórios (com exportação), sem alterar dados |

- Senha: mínimo de 8 caracteres, com letras e números. São guardadas apenas como hash scrypt com sal.
- 5 tentativas erradas bloqueiam o usuário por 15 minutos.
- A sessão expira após 30 minutos sem uso (`CLOUD_FINANCE_SESSAO_MIN`). Atualizar a página (F5) também pede login.
- Usuários não são apagados, só desativados, e sempre existe pelo menos um administrador ativo.
- Entradas, saídas e tentativas recusadas ficam na Auditoria, e cada ação registra o usuário que a fez.

## Atualizar uma versão já instalada

Substitua as pastas `core`, `ui`, `tests`, `scripts` e os arquivos `app.py`,
`requirements.txt` e `README.md`. **Não apague a pasta `dados`** — é nela que
estão as importações já feitas. Depois rode `pip install -r requirements.txt`.

## Testes

```
python -m unittest discover -s tests -t . -v
```
Os testes usam a planilha fictícia `dados/amostra_ficticia.xlsx` e conferem os
totais com o rodapé da própria planilha.

## Importação pela linha de comando

```
python scripts/importar.py dados/amostra_ficticia.xlsx --data-entrada 09/11/2026            (só prévia)
python scripts/importar.py dados/amostra_ficticia.xlsx --data-entrada 09/11/2026 --confirmar (grava)
```

## Regras financeiras em vigor

| Regra | Definição | Origem |
|---|---|---|
| Receita recebida | Todos os registros importados | Usuária, 10/11/2026 |
| Data de referência | "Data de entrada" informada na importação | Usuária, 10/11/2026 |
| Qtd. de pagamentos | ID Parcela distintos (linhas de split contam 1 vez) | Usuária, 10/11/2026 |
| Valores | Soma de todas as linhas (cada linha de split tem sua parte) | Planilha |
| Chave do registro | ID da Venda (único por linha) | Planilha |
| Validação | Valor Líquido = Valor Bruto − Custo Financeiro (sinaliza, não corrige) | Especificação |
| Classificação | Prefixo do Nº do Pedido: B, RC, INV, RAE, DES, ENP, DCR (regras editáveis); sem regra = "Não identificado" | Usuária, 10/11/2026 |
| Receita CENSEC | CENSEC = BuscaTestamento | Usuária, 10/11/2026 |
| Pix/Cartão/Boleto | Meio "Boleto Híbrido" = Boleto, mesmo quitado via Pix; senão Forma: PIX = Pix, Crédito/Débito = Cartão | Usuária, 10/11/2026 |
| Data de processamento (boletos) | Data de entrada informada na importação | Usuária, 10/11/2026 |
| Tarifa parcela Express | Corresponde ao Custo Financeiro | Usuária, 17/11/2026 |
| Baixa contábil | Não utilizada | Usuária, 17/11/2026 |
| Inclusão por status | Todos os status entram; pode-se retirar status em Configurações | Especificação |
| Conflitos | Registro original nunca é sobrescrito sem decisão da usuária | Especificação |
| Acesso | 1 administrador, 2 operadores, 3 diretores com perfil Consulta | Usuária, 17/11/2026 |
| Exclusão de importação | Remove só os registros que entraram por ela, com backup automático antes; fica no histórico como excluída | Usuária, 17/11/2026 |

## Estrutura

| Pasta/arquivo | Conteúdo |
|---|---|
| `app.py` | Menu lateral e navegação |
| `core/` | Regras e cálculos (sem interface): importação, classificação, indicadores, conciliação, relatórios, banco |
| `ui/` | Telas: Dashboard, Receita Diária, Boletos, Transações, Conciliação, Relatórios, Importações, Configurações |
| `tests/` | 71 testes automáticos com a planilha fictícia |
| `dados/` | Banco de dados e backups (**não apagar**) |
| `deploy/` | `pasta_rede/` (atalhos da pasta Z:) e alternativas de servidor: NSSM, IIS, systemd, nginx, Docker |
| `.streamlit/` | Configuração do Streamlit (limite de upload, tema, sem estatísticas externas) |

Valores são guardados em centavos (inteiros) para evitar erro de arredondamento;
o conteúdo original de todas as colunas é guardado sem alteração.
