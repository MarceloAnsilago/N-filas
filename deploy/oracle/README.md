# CI/CD do Nfilas na Oracle

O GitHub Actions executa os testes Python 3.12 e JavaScript em runner hospedado pelo GitHub, com SQLite temporário. A Oracle consulta a ponta da `main` e o resultado de `.github/workflows/ci.yml` pela API pública do GitHub, sem token. Apenas uma execução de `push` concluída com sucesso para aquele SHA autoriza a publicação. O script confere a ponta e o resultado novamente depois de preparar o ambiente. Se a revisão estiver pendente, falhar ou a consulta falhar, o serviço atual continua em uso. [API do GitHub Actions](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)

## Instalação

Em uma janela de manutenção, use um checkout **revisado** do N-filas fora de `/opt/nfilas/app`, no commit que introduz a automação. Execute os comandos a partir da raiz desse checkout. Revise o script, as unidades e a regra sudoers antes de instalá-los.

Confira a unidade existente com os comandos abaixo. O `nfilas.service` deve executar como `nfilas`, usar `/opt/nfilas/app` como diretório de trabalho e iniciar via `/opt/nfilas/.venv`. Confirme também que nenhuma diretiva da unidade executa código gravável por `nfilas` com privilégios de root, inclusive comandos auxiliares com prefixos `+` ou `!`. O `.env` deve definir `PAINEL_DB_PATH` como caminho absoluto de um banco existente em `/opt/nfilas/data`, sem sobrescrita por configuração do serviço. Confira esse valor diretamente no servidor e mantenha o conteúdo do `.env` privado. O diretório de dados deve ser local, sem links simbólicos e com `nfilas.service` como único gravador. Reserve espaço para o ambiente novo e o backup.

```bash
sudo systemctl show nfilas.service -p User -p Group -p WorkingDirectory
sudo systemctl is-active nfilas.service
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:8081/login
sudo apt-get install git python3.12-venv curl
sudo -u nfilas test -r /opt/nfilas/app/.env
sudo -u nfilas test -w /opt/nfilas/data
sudo -u nfilas test -w /opt/nfilas
```

Se apenas o último teste falhar, conceda acesso ao diretório pai do Nfilas com `sudo chown nfilas:nfilas /opt/nfilas`, sem aplicar a mudança recursivamente. O script move os diretórios de aplicação e ambiente virtual dentro desse mesmo sistema de arquivos. Mantenha dados e configurações locais persistentes em `/opt/nfilas/data` e no `.env`. Arquivos adicionais e alterações locais dentro do checkout anterior ficam na cópia de rollback. Confira a leitura do `.env` e a escrita dos bancos existentes antes de prosseguir.

```bash
sudo install -d -o root -g root -m 0755 /usr/local/lib/nfilas-deploy
sudo install -o root -g root -m 0644 deploy/oracle/deploy.py \
  /usr/local/lib/nfilas-deploy/deploy.py
sudo install -o root -g root -m 0644 deploy/oracle/nfilas-deploy.{service,timer} \
  /etc/systemd/system/
sudo visudo -cf deploy/oracle/nfilas-deploy.sudoers
sudo install -o root -g root -m 0440 deploy/oracle/nfilas-deploy.sudoers \
  /etc/sudoers.d/nfilas-deploy
sudo visudo -c
sudo systemd-analyze verify /etc/systemd/system/nfilas-deploy.{service,timer}
sudo systemctl daemon-reload
```

A regra sudoers permite ao usuário `nfilas` somente iniciar e parar `nfilas.service` por meio dessa regra. A consulta, a preparação e a execução da aplicação usam o usuário `nfilas`. Atualizações do próprio script, das unidades ou da regra sudoers requerem repetir a instalação dos arquivos a partir de uma revisão conferida.

## Primeira publicação e validação

Confira o resultado verde do commit na [aba Actions](https://github.com/MarceloAnsilago/N-filas/actions/workflows/ci.yml) e rode a primeira consulta manualmente. Procure por `Publicado <SHA>` no diário e compare o SHA ao da execução aprovada. O serviço para durante o backup e a troca, depois deve responder HTTP 200 em `/login`. A consulta é repetida nos minutos pares depois que o timer é habilitado.

```bash
sudo systemctl start nfilas-deploy.service
sudo journalctl -u nfilas-deploy.service -n 50 --no-pager
sudo systemctl is-active nfilas.service
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  https://nfilas.celosmg.com.br/login
sudo systemctl enable --now nfilas-deploy.timer
systemctl list-timers nfilas-deploy.timer
```

## Rollback

Após parar o serviço, o script registra um snapshot de cada SQLite, incluindo os bancos por unidade, usando a API de backup do SQLite e verificando a integridade. O deploy copia o `.env` para a nova aplicação com permissão `0600`. Após falha no início ou no HTTP, o script restaura a aplicação, o ambiente, o `.env` anterior e o snapshot dos bancos. Se a publicação for interrompida depois de registrar a operação, a próxima consulta tenta concluir a recuperação antes de verificar novos commits.

Para reverter a última publicação automatizada, pare o timer e aguarde eventual execução em andamento terminar. Preserve separadamente os dados atuais se precisar recuperar registros recentes. **O rollback restaura os bancos ao instante anterior à publicação e elimina alterações posteriores nesses bancos.**

```bash
sudo systemctl disable --now nfilas-deploy.timer
sudo systemctl status nfilas-deploy.service
sudo -u nfilas /usr/bin/python3.12 -I /usr/local/lib/nfilas-deploy/deploy.py rollback
sudo systemctl is-active nfilas.service
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:8081/login
```

Um rollback bloqueia a tentativa do CI que originou a publicação. Um novo `push` aprovado ou uma nova tentativa bem-sucedida do CI pode autorizar uma nova publicação. Os backups ficam em `/opt/nfilas/.deploy` e contêm dados e configurações privados. Monitore o espaço. Preserve o diretório ativo, os diretórios referenciados por ambientes virtuais e a cadeia de backups que deseja manter.

## Desativação

Para interromper a automação, execute `sudo systemctl disable --now nfilas-deploy.timer` e aguarde qualquer publicação em curso. A versão ativa continua servindo. Para retirar a instalação, conclua qualquer operação pendente e execute os comandos abaixo. Preserve `/opt/nfilas/.deploy` porque o ambiente virtual ativo pode estar nesse diretório.

```bash
sudo rm /etc/systemd/system/nfilas-deploy.service \
  /etc/systemd/system/nfilas-deploy.timer /etc/sudoers.d/nfilas-deploy \
  /usr/local/lib/nfilas-deploy/deploy.py
sudo systemctl daemon-reload
```
