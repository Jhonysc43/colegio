# Implantação — Receita Colégio Notarial do Brasil

**Forma escolhida: pasta de rede (Z:).** O programa e os dados ficam na pasta compartilhada do
servidor; cada pessoa abre o sistema no próprio computador. Só quem tem acesso à pasta consegue
usar o sistema. Não é preciso instalar nada no servidor.

```
 Computador de cada usuário                      Servidor de arquivos (Z:)
 ┌──────────────────────────────────┐             ┌────────────────────────────────────────┐
 │ atalho "Receita CNB"             │             │ Z:\ReceitaCNB\                         │
 │   → Python + bibliotecas locais  │  lê o       │   Abrir Receita CNB.bat                │
 │     (%LOCALAPPDATA%\ReceitaCNB)  │  programa   │   Instalar neste computador.bat        │
 │   → navegador em localhost:8501  │ ◄────────── │   app\   (programa)                    │
 │     (só este computador acessa)  │  lê e grava │   dados\cloud_finance.db (dados)       │
 │                                  │ ──────────► │   dados\backups\automaticos\ (diário)  │
 └──────────────────────────────────┘             └────────────────────────────────────────┘
```

## A. Pasta de rede — passo a passo

### A.1 Montar a pasta (uma vez, no computador da administradora)

1. Peça a todos para fecharem o sistema, se estiver aberto.
2. Descompacte o pacote do sistema no computador (por exemplo, por cima da pasta atual
   `cloud_finance`, mantendo a pasta `dados`).
3. Abra a pasta `deploy\pasta_rede` e dê dois cliques em **Montar pasta do sistema.bat**.
4. Confirme a pasta de destino (padrão `Z:\ReceitaCNB`, basta teclar Enter).
5. O script copia o programa para `Z:\ReceitaCNB\app`, coloca os dois atalhos na raiz e, na
   primeira vez, **leva os dados atuais** do computador para `Z:\ReceitaCNB\dados`. A cópia é
   conferida e o script nunca substitui dados que já estejam na rede.
6. A partir daí, **use sempre a versão da rede**. A cópia local deixa de ser usada.

### A.2 Preparar cada computador (uma vez por computador)

1. O computador precisa de **Python 3.11 ou mais recente** (python.org, com "Add Python to
   PATH" marcado). A instalação por usuário não exige administrador; a TI também pode distribuir.
2. Dê dois cliques em **Z:\ReceitaCNB\Instalar neste computador.bat**. Ele cria o ambiente do
   sistema em `%LOCALAPPDATA%\ReceitaCNB`, instala as bibliotecas e cria o atalho
   **Receita CNB** na Área de Trabalho. Leva alguns minutos e precisa de internet, a não ser
   que exista a pasta `Z:\ReceitaCNB\pacotes` (item 7).

### A.3 Usar

Dê dois cliques no atalho **Receita CNB**. Uma janela preta abre e, em seguida, o navegador
com a tela de login. **A janela preta precisa ficar aberta** enquanto o sistema é usado. Para
sair: feche o navegador e depois a janela. Se clicar no atalho com o sistema já aberto, ele só
abre o navegador de novo.

### A.4 Permissões da pasta (TI)

O acesso ao sistema é controlado pela permissão na pasta. Sugestão: um grupo do Active
Directory, por exemplo "Receita CNB", com as 6 pessoas.

| Pasta | Grupo "Receita CNB" | Administradora |
|---|---|---|
| `Z:\ReceitaCNB` e `app\` | Leitura e execução | Modificar (para instalar atualizações) |
| `Z:\ReceitaCNB\dados\` | **Modificar**, também para os diretores, porque o login grava a auditoria | Modificar |

Quem não está no grupo não consegue abrir o programa nem ler o arquivo de dados. Dentro do
sistema continuam valendo o login e os perfis (Administrador, Operador, Consulta).

### A.5 Proteções do modo pasta de rede

Um banco SQLite numa pasta compartilhada exige cuidados, porque o travamento de arquivos pela
rede nem sempre é confiável. O sistema detecta sozinho que o banco está na rede e:

- usa o modo de gravação compatível com rede (journal DELETE; o modo WAL não funciona em rede);
- usa uma **tranca de gravação** (`cloud_finance.db.trava`): só um computador grava por vez, e os
  outros esperam a vez. Uma tranca esquecida por um computador desligado é removida em 10 minutos;
- na primeira abertura de cada dia, **confere a integridade** do arquivo e faz o **backup do dia**
  em `dados\backups\automaticos` (30 dias guardados; os 7 mais recentes nunca são apagados);
- se o arquivo apresentar problema, **bloqueia as gravações** e mostra a **tela de recuperação**:
  o administrador escolhe o backup e confirma com o usuário e a senha dele. O arquivo danificado é
  guardado em `dados\backups\antes_de_restaurar`.

Recomendações: incluir `Z:\ReceitaCNB\dados` na rotina de backup da empresa; excluir a pasta da
varredura em tempo real do antivírus, se possível; não abrir nem copiar o arquivo `.db` com o
sistema em uso (use Configurações → Backup); e nunca usar o recurso "Arquivos Offline" do
Windows nessa pasta.

### A.6 Atualizar para uma versão nova

1. Todos fecham o sistema.
2. A administradora descompacta a versão nova no computador dela e roda de novo
   **deploy\pasta_rede\Montar pasta do sistema.bat**. O programa é substituído; os dados não.
3. Se a versão nova pedir, cada computador roda de novo **Instalar neste computador.bat**.

---

**As opções abaixo (B, C e D) são alternativas**, caso no futuro a TI prefira rodar o sistema
como serviço num servidor, com acesso pelo navegador via HTTPS:

```
 Navegador dos usuários (rede interna)
        │  HTTPS (443)
        ▼
 Proxy reverso: IIS (Windows) ou nginx (Linux)  ── certificado da empresa
        │  HTTP local (127.0.0.1:8501), com WebSocket
        ▼
 Serviço "ReceitaCNB" (python -m streamlit run app.py)
        │
        ▼
 Banco: D:\ReceitaCNB\dados\cloud_finance.db  ──►  backup diário: D:\ReceitaCNB\backups
```

## 1. Requisitos (opções B, C e D)

| Item | Mínimo |
|---|---|
| Sistema operacional | Windows Server 2016 ou mais recente, ou Linux (Ubuntu 22.04+, RHEL 9+) |
| Python | 3.11 ou mais recente (recomendado 3.12) |
| Memória | 2 GB livres |
| Disco | 1 GB para o sistema + espaço para backups (cada backup tem o tamanho do banco) |
| Rede | Porta 443 aberta na rede interna; a porta 8501 só precisa ser acessível pelo proxy |
| Certificado | Certificado HTTPS da empresa para o nome interno (ex.: `receita.cnb.local`) |
| Internet | Só durante a instalação, para baixar os pacotes Python (há alternativa offline, item 7) |

Pacotes Python (em `requirements.txt`): streamlit, pandas, openpyxl, plotly. A biblioteca
padrão cobre o banco (sqlite3) e as senhas (hashlib.scrypt).

## 2. Opção B — Windows Server (serviço + IIS)

Arquivos prontos em `deploy\windows\`.

1. **Instale o Python** (python.org), marcando "Add Python to PATH" e "Install for all users".
2. **Copie o sistema** para `C:\ReceitaCNB\app` (a pasta que contém `app.py`).
3. **Crie o ambiente e instale os pacotes** (Prompt de Comando como Administrador):
   ```
   cd C:\ReceitaCNB\app
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
4. **Ajuste `deploy\windows\configuracao.bat`**: caminhos do sistema, do banco e dos backups.
   Mantenha o banco **fora** da pasta do sistema (ex.: `D:\ReceitaCNB\dados`), para que uma
   atualização nunca toque nos dados.
5. **Leve os dados atuais** para o caminho do banco (item 5 deste guia).
6. **Teste manualmente**: rode `deploy\windows\iniciar_servidor.bat` e abra
   `http://localhost:8501` no servidor. Feche com Ctrl + C.
7. **Instale o serviço**: baixe o NSSM (https://nssm.cc), coloque `nssm.exe` no PATH e rode
   `deploy\windows\instalar_servico.bat` como Administrador. Ele:
   - cria o serviço **ReceitaCNB**, com início automático e log em `C:\ReceitaCNB\app\logs`;
   - agenda a tarefa **"ReceitaCNB - Backup diario"** às 22h.
8. **Configure o HTTPS no IIS**:
   1. Instale os recursos do IIS **WebSocket Protocol**, **URL Rewrite** e
      **Application Request Routing (ARR)**.
   2. Em IIS Manager → servidor → Application Request Routing Cache → Server Proxy Settings,
      marque **Enable proxy**.
   3. Crie um site com binding HTTPS (porta 443) e o certificado da empresa, apontando para uma
      pasta vazia (ex.: `C:\ReceitaCNB\iis`).
   4. Copie `deploy\windows\web.config` para essa pasta.
   5. Em `configuracao.bat`, troque `STREAMLIT_SERVER_ADDRESS` para `127.0.0.1`, rode
      `instalar_servico.bat` de novo e reinicie o serviço (`nssm restart ReceitaCNB`). Assim,
      o acesso passa a ser só pelo IIS.
9. **Firewall**: libere a porta 443 para a rede interna. Não libere a 8501 para a rede.

Comandos úteis: `nssm status ReceitaCNB`, `nssm restart ReceitaCNB`, `nssm stop ReceitaCNB`.

## 3. Opção C — Linux (systemd + nginx)

Arquivos prontos em `deploy/linux/`.

```bash
sudo useradd --system --create-home receitacnb
sudo mkdir -p /opt/receita-cnb/app /var/lib/receita-cnb /var/backups/receita-cnb
sudo cp -r . /opt/receita-cnb/app                     # a partir da pasta do sistema
sudo chown -R receitacnb /opt/receita-cnb /var/lib/receita-cnb /var/backups/receita-cnb
cd /opt/receita-cnb/app
sudo -u receitacnb python3 -m venv .venv
sudo -u receitacnb .venv/bin/pip install -r requirements.txt

sudo cp deploy/linux/receita-cnb*.service deploy/linux/receita-cnb-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now receita-cnb receita-cnb-backup.timer

sudo cp deploy/linux/nginx-receita-cnb.conf /etc/nginx/sites-available/receita-cnb
sudo ln -s /etc/nginx/sites-available/receita-cnb /etc/nginx/sites-enabled/
# ajuste server_name e os caminhos do certificado no arquivo, depois:
sudo nginx -t && sudo systemctl reload nginx
```

O serviço já escuta só em `127.0.0.1`. Logs: `journalctl -u receita-cnb -f`.

## 4. Opção D — Docker

Para servidores Linux com Docker. Arquivos em `deploy/docker/`.

```bash
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

O banco fica no volume `receita-dados` (`/dados` dentro do contêiner), e a porta 8501 fica
publicada só em `127.0.0.1`. Use o nginx do item 3 para o HTTPS. Backup diário pelo cron do host:

```
0 22 * * * docker compose -f /caminho/deploy/docker/docker-compose.yml exec -T receita-cnb python scripts/backup_automatico.py
```

## 5. Levar os dados atuais para o servidor (opções B, C e D)

Hoje os dados estão no computador da administradora.

1. No computador atual, entre como administradora, vá em **Configurações → Backup**, clique em
   **Gerar backup agora** e depois em **Baixar uma cópia do backup**.
2. Copie o arquivo baixado (`receita_cnb_AAAAMMDD_HHMMSS.db`) para o servidor, com o nome e
   o caminho definidos em `CLOUD_FINANCE_DB` (ex.: `D:\ReceitaCNB\dados\cloud_finance.db`).
3. Inicie o serviço. Todas as importações, regras, classificações, usuários e a auditoria vêm
   juntos. As pessoas entram com os mesmos usuários e senhas.
4. A partir daí, **pare de usar a cópia local** para não haver dois bancos diferentes.

Se preferir começar vazio, basta não copiar o banco: no primeiro acesso, o sistema pede para
criar o administrador.

## 6. Backups

- **Automático:** `scripts/backup_automatico.py`, agendado diariamente às 22h. Cada backup é um
  único arquivo `.db` completo. São mantidos 30 dias (`CLOUD_FINANCE_BACKUP_DIAS`), e os 7 mais
  recentes nunca são apagados. O script termina com código 1 se falhar, para o agendador alertar.
- **Recomendado:** inclua a pasta de backups na rotina de backup corporativa, ou aponte
  `CLOUD_FINANCE_BACKUP_DIR` para uma pasta de rede.
- **Manual:** o administrador também pode gerar e baixar backups em Configurações → Backup.
- **Restaurar:** em Configurações → Backup, envie o arquivo `.db`. Ou, com o serviço parado,
  copie o backup por cima do arquivo do banco e apague os arquivos `-wal` e `-shm` ao lado dele.

## 7. Instalação sem internet

Num computador com internet e o mesmo sistema operacional e a mesma versão do Python:

```
pip download -r requirements.txt -d pacotes
```

No modo pasta de rede, coloque a pasta em `Z:\ReceitaCNB\pacotes`: o "Instalar neste
computador.bat" passa a usá-la sozinho, sem internet. Nas opções de servidor, copie a pasta
`pacotes` para o servidor e instale:

```
.venv\Scripts\pip install --no-index --find-links pacotes -r requirements.txt
```

## 8. Atualizar para uma versão nova (opções B, C e D)

1. Faça um backup (Configurações → Backup ou `backup_automatico.py`).
2. Pare o serviço (`nssm stop ReceitaCNB` ou `systemctl stop receita-cnb`).
3. Substitua na pasta do sistema: `app.py`, `core`, `ui`, `scripts`, `tests`, `deploy`,
   `.streamlit`, `requirements.txt`. O banco fica em outra pasta e não é tocado.
4. Rode `pip install -r requirements.txt` no ambiente `.venv`.
5. Opcional: rode os testes (`.venv\Scripts\python -m unittest discover -s tests -t .`).
6. Inicie o serviço. Ajustes de esquema e de regras novas são aplicados sozinhos ao iniciar.

## 9. Checklist depois da implantação (opções B, C e D)

- [ ] `https://<nome interno>/_stcore/health` responde `ok`
- [ ] A tela de login abre pelo endereço HTTPS, com o cadeado do certificado
- [ ] `http://<servidor>:8501` **não** abre a partir de outro computador da rede (acesso só pelo proxy)
- [ ] A administradora entra e vê os dados que existiam no computador dela
- [ ] Um operador importa uma planilha de teste e a vê no Dashboard
- [ ] Um diretor (perfil Consulta) entra e não vê Importações nem Configurações
- [ ] Depois de reiniciar o servidor, o sistema volta sozinho
- [ ] No dia seguinte, existe um backup novo na pasta de backups, e o `backup.log` não tem erros

## 10. Solução de problemas

No modo pasta de rede:

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Este computador ainda não foi preparado" | Falta rodar o instalador nesse computador | Rode `Instalar neste computador.bat` |
| "Python 3.11 ou mais recente não foi encontrado" | Python ausente ou antigo | Instale pelo python.org com "Add Python to PATH" |
| "Port 8501 is already in use" | Outro programa usa a porta | Feche o outro programa, ou troque `PORTA` no `Abrir Receita CNB.bat` |
| Gravação demora alguns segundos | Outro computador está gravando (tranca) | Normal: o sistema espera a vez, por até 2 minutos |
| "Outra gravação está em andamento há muito tempo" | Um computador travou no meio de uma gravação | Aguarde: a tranca é liberada em até 10 minutos |
| Tela de recuperação ao abrir | O arquivo de dados apresentou problema | O administrador restaura o backup mais recente por essa tela |

Nas opções de servidor:

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| A página abre mas fica em "Please wait..." ou "Connecting" | O proxy não repassa o WebSocket | IIS: instale "WebSocket Protocol" e confira o ARR. nginx: confira `Upgrade` e `Connection` |
| Erro 413 ao importar planilha | O limite de upload do proxy é menor que o do sistema | IIS: `maxAllowedContentLength`; nginx: `client_max_body_size` (os arquivos já trazem 200 MB) |
| Todos precisam entrar de novo de repente | O serviço reiniciou (as sessões ficam na memória) | Normal após reinício ou atualização; veja o log se acontecer sem motivo |
| "database is locked" no log | Gravação muito longa de outra sessão, ou antivírus segurando o arquivo | O sistema espera até 30 s; exclua a pasta do banco da varredura em tempo real do antivírus |
| O serviço não inicia | Caminho do Python ou do banco errado | Rode `iniciar_servidor.bat` à mão para ver a mensagem; confira `configuracao.bat` |

## 11. Segurança

- Senhas guardadas apenas como hash scrypt com sal; não há usuário nem senha padrão no código.
- 5 tentativas erradas bloqueiam o usuário por 15 minutos; a sessão expira após 30 minutos sem uso.
- Todas as ações relevantes ficam na auditoria (Configurações → Auditoria).
- Acesso só pela rede interna e por HTTPS. A porta 8501 escuta apenas localmente quando há proxy.
- O Streamlit não envia estatísticas de uso para fora (`gatherUsageStats = false`).
- O arquivo do banco contém os dados financeiros: restrinja a pasta ao usuário do serviço e aos
  administradores do servidor, e trate os backups com o mesmo cuidado.
