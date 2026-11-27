# Gfilas

Painel de senhas em Flask com painel digital, preparado para rodar localmente e em Fly.io com banco SQLite persistente.

## Variaveis de ambiente

- `SECRET_KEY`: chave do Flask usada para sessoes. Troque por um valor longo e secreto.
- `PAINEL_DB_PATH`: caminho para o arquivo SQLite (`ultima_senha.db` por padrao; o deploy em Fly.io aponta para `/data/ultima_senha.db`).
- `PAINEL_UNIDADE_PADRAO`: rotulo exibido quando nenhum nome de unidade e informado.
- `PAINEL_USUARIO_PADRAO`: usuario exibido quando o operador nao for informado.
- `PAINEL_FUSO_HORARIO`: fuso usado nos carimbos de data/hora (`America/Sao_Paulo`, `Etc/GMT+3`, etc.).
- `PAINEL_MAX_ULTIMAS`: quantas senhas encerradas aparecem no painel digital.
- `PAINEL_VIDEO_URL`, `PAINEL_VIDEO_MUTED`, `PAINEL_YT_PLAYLIST_URL`, `PAINEL_YT_PLAYLIST_ID`, `PAINEL_YT_MUTED`: parametros opcionais para o conteudo em tela cheia do painel.

Um exemplo de todas as variaveis acima esta em `.env.example`.

## Rodar local

1. Crie o ambiente virtual: `python -m venv venv`.
2. Ative o ambiente (`venv\Scripts\activate` no Windows, `source venv/bin/activate` no macOS/Linux).
3. Instale as dependencias: `pip install -r requirements.prod.txt`.
4. Copie o exemplo de configuracao: `copy .env.example .env` (Windows) ou `cp .env.example .env` (macOS/Linux) e ajuste as variaveis conforme o ambiente.
5. (Opcional) `set FLASK_ENV=development` (Windows) ou `export FLASK_ENV=development` (macOS/Linux).
6. Execute `python -m flask run --app run.py --debug` (ou `python run.py`) para subir o servidor em `http://localhost:5000`.

O SQLite (`ultima_senha.db`) e criado automaticamente quando o aplicativo inicia.

## Deploy (Fly.io)

### Login por unidade

- Entre no Super Admin em `/admin/login` com a conta administrativa já configurada. Em `/admin`, cadastre o estabelecimento e copie a senha administrativa temporária exibida na confirmação. O nome do estabelecimento será o login.
- O responsável entra em `/unidade/admin/login`, troca a senha temporária e acessa as configurações do próprio estabelecimento. Para uma unidade já cadastrada, use **Gerar senha administrativa** no Super Admin.
- O login operacional em `/login` continua disponível para balcão e TV. As senhas operacionais existentes são preservadas. Para novas unidades que precisam desse acesso, preencha a senha de balcão e TV no cadastro.
- **Cadastre primeiro a unidade que ja utiliza o sistema.** A primeira conta recebe o banco existente, com suas filas e historico. As demais comecam com bancos vazios.
- Todas as telas exigem login. A fila, as chamadas, os contadores, o historico, as configuracoes e os eventos do painel ficam separados por unidade.
- Use **Sair** para trocar de unidade. Abas do mesmo perfil do navegador compartilham o login; para usar duas unidades simultaneamente, utilize perfis separados.
- `/admin` permite redefinir senhas administrativas e ativar ou desativar estabelecimentos. A redefinição encerra as sessões administrativas daquele estabelecimento.
- O arquivo definido em `PAINEL_DB_PATH` guarda o cadastro de logins e os dados da primeira unidade. Os bancos adicionais ficam ao lado dele, na pasta `<nome_do_banco>_unidades`, identificados por ID. Inclua essa pasta no backup e no volume persistente do servidor.
- As senhas sao armazenadas com hash. Defina uma `SECRET_KEY` secreta para as sessoes; sem uma chave personalizada, o app gera um arquivo `.session_secret` ao lado do banco, que tambem deve persistir entre reinicios.
- Reinicie o servidor depois de instalar a atualizacao.

### Painel em tempo real (SSE)

O `/painel` recebe chamadas, rechamadas e encerramentos por `/painel/events`, sem consultar `/painel/status` a cada segundo. O servidor consulta o SQLite ao abrir a conexao e ao alterar as senhas; os sinais de manutencao da conexao nao consultam o banco. Ao reconectar, o painel recebe o estado atual. Anuncios antigos ocorridos durante uma queda nao sao reproduzidos em sequencia.

Execute **um unico processo/replica** da aplicacao: as notificacoes sao compartilhadas em memoria entre as threads desse processo. O Docker usa Gunicorn com `-w 1 --threads 32`; o `start_server.bat` usa Waitress com 32 threads. Cada painel conectado ocupa uma thread; mantenha capacidade livre para os atendentes. Para varios processos ou servidores, sera necessario um canal compartilhado de eventos, como Redis. Alteracoes feitas diretamente no SQLite por ferramentas externas nao geram avisos.

Na Oracle ou em outro servidor com Nginx, configure a rota de eventos no mesmo dominio do site:

```nginx
location /painel/events {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 60s;
}
```

Ajuste a porta ao servidor da aplicacao. Reinicie o servidor e atualize as abas dos paineis apos instalar a atualizacao.

Para validar sem alterar o banco real: `python -m unittest discover -s tests -v`.

Referencias: [streaming no Flask](https://flask.palletsprojects.com/en/stable/patterns/streaming/) e [SSE no navegador](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events).

### Publicar no Fly.io

1. Instale e autentique-se no `flyctl`.
2. Execute `flyctl deploy -a senhasflask`; o `Dockerfile` utiliza `requirements.deploy.txt` para instalar somente o necessario em producao.
3. O `fly.toml` ja configura o volume `/data` (montado como `app_data`) e define `PAINEL_DB_PATH=/data/ultima_senha.db` para manter o SQLite persistente.
4. Para ver logs ou diagnosticar problemas, use `flyctl logs -a senhasflask` e ajuste variaveis via `flyctl secrets` ou pelo painel da Fly.

## Operação

- Abra `/senhas` para emitir senhas normais e preferenciais. O número aparece na tela após a emissão.
- Abra `/chamar` para chamar as senhas da unidade.
- Abra `/painel` no navegador, mova a janela para o segundo monitor e use F11 para exibir em tela cheia.

## Observacoes

- O repositorio tambem inclui scripts Windows (`bootstrap_venv.bat`, `start_server.bat`) para facilitar o bootstrap em estacoes Windows.
- Use `requirements.prod.txt` no ambiente local e mantenha `requirements.deploy.txt` alinhado ao que sera instalado dentro do container.
