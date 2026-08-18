# Checklist de lançamento

Levantado em 2026-07-27, incluindo uma review de segurança e uma review do fluxo
de pagamentos. Atualizado em 2026-08-18. Estado do produto: **245 testes
passando**, fluxo completo do SPEC implementado.

Marcadores: `[código]` = programar de verdade · `[seg]` = achado da review de
segurança · `[pag]` = achado da review de pagamentos.

Resultado das reviews, em uma linha: **nenhum achado crítico de segurança**
(sem RCE, sem bypass de auth, sem IDOR, sem injeção) — mas o **fluxo de
pagamentos tinha dois furos que sangravam dinheiro**, ambos fechados em
2026-08-01 junto com os dois achados de segurança do mesmo bloco.

**Não sobra item `[código]` nos blocos 1-2.** O que falta pra lançar é ops
(domínio, Paddle em produção, servidor) mais UMA validação: exercitar upgrade e
renovação de verdade no sandbox — ver a ressalva nos dois itens de pagamento
abaixo, os payloads reais nunca foram observados.

**Atualização 2026-08-05 (commit `f1f5848`, "security hardening").** Quatro
itens dos blocos 3-4 foram fechados ANTES do gatilho, porque o mesmo mergulho no
código que fechou um encontrou os outros: verificação de email, starvation do
threadpool, `error_message` cru e o path traversal do `LocalStorage`. Junto
vieram quatro coisas que não estavam nesta lista (tetos de fila, `SecretStr` nos
segredos, download em streaming, upload malformado virando 500) — todas
registradas como `[x]` no bloco 3, para a lista não continuar mentindo sobre o
que existe. **Nada disso mudou o que falta pra lançar: segue sendo ops.**

**Atualização 2026-08-18 — a confirmação de email virou pré-requisito.** Era um
gate mole (conta não confirmada usava tudo, só não tinha crédito); agora é
duro, decidido pelo usuário: `/images/upload` recusa endereço não confirmado
(403) e `/billing/plans` não entrega o `paddle_client_token`, que é o que deixa
o `Paddle.Initialize` rodar — o checkout é aberto pelo Paddle.js no navegador,
então negar o token É a barreira, não há rota pra recusar. `/billing/change`
recusa com 403 junto; `/billing/cancel` e `/billing/resume` continuam abertos
de propósito, porque trancar alguém numa assinatura que ele não consegue
cancelar é pior que o problema. O upload também passou a exigir saldo que cubra
o custo daquela imagem (`job_cost` a 2x já é o preço final), em vez de guardar
bytes que nenhum job vai ler. No front, o dashboard deixou de aparecer:
`initShell` manda conta não confirmada pra `/verify`, que virou sala de espera
(reenviar o link, trocar de conta) além de página do token — a faixa amarela no
`base.html` saiu junto, não teria mais leitor. **Isso é apresentação, não
barreira:** redirect é sugestão pro navegador e nada pro `curl`, as barreiras
de verdade são as da API acima. Testes: `tests/test_upload_gating.py` (6), mais
4 em `tests/test_billing.py` e 2 em `tests/test_web.py`. **Consequência pro lançamento: o item do Resend
abaixo deixou de ser sobre recuperação de senha e virou o gargalo de todo o
funil — está reescrito.**

Servidor: Hetzner. **Mínimo 8 GB de RAM** — o `post_processor` consome ~100 MB
por megapixel de saída (medido), e o pior caso permitido hoje (`max_image_px=3072`,
saída 6144×4608) tem pico de ~3,0 GB num único job. Numa máquina de 4 GB isso
encosta no teto mesmo com `max_concurrent_jobs=1`, e o OOM killer derruba o
uvicorn inteiro, não só o job.

**Decidido 2026-07-29:** ir para 8 GB em vez de otimizar o `color_match` (que
fica adiado no bloco 4). **Executado 2026-08-05** com uma máquina nova de 8 GB
que vai hospedar TODOS os projetos do usuário (Next.js atual + mais um + dois
Python + este) — servidor dedicado foi cogitado e recusado por custo.

Por ser compartilhada, o `mem_limit` do compose deixa de ser higiene e vira
isolamento: sem ele, um OOM deste app derruba os outros junto. E o orçamento
muda — cabe `max_concurrent_jobs=1` com `mem_limit: 3.5g` e `cpus: 2.0`, não os
2 jobs que uma caixa dedicada aguentaria. Medido na imagem real em 2026-08-05:
**100 MB em repouso**; os ~3 GB são um pico de 60–90s durante o job.

---

## Bloco 1 — começar HOJE (é fila de terceiro, não trabalho seu)

A aprovação da Paddle é o único item que depende de outra pessoa e pode levar
dias. Tudo no bloco 2 cabe dentro dessa espera.

- [ ] Registrar domínio + apontar DNS
- [ ] Páginas de termos, privacidade e política de reembolso
      **RASCUNHO FEITO 2026-08-05** — falta o que só você pode dar: revisar o
      texto e preencher os `LEGAL_*` no `.env`.
      `/terms`, `/privacy`, `/refunds` (templates próprios, sem `base.html`:
      o `app.js` chuta visitante deslogado pro `/login`, e o revisor da Paddle
      é exatamente isso). Linkadas do `/login` e do modal de checkout.
      O conteúdo saiu do código, não de template genérico: cota que reseta sem
      acumular, saldo que morre no cancelamento, custo 1/2/4/8 por resolução de
      saída, refund automático de job que falha, proração no upgrade, Paddle
      como merchant of record, e a lista real de sub-processadores (Replicate
      — pra onde a foto do usuário VAI —, R2, Neon, Resend, Paddle, Hetzner).
      A privacidade já descreve a exclusão self-service e o que sobrevive.
      Identidade jurídica virou config (`LEGAL_ENTITY`, `LEGAL_ADDRESS`,
      `LEGAL_CONTACT_EMAIL`, `LEGAL_GOVERNING_LAW`): vazio aparece como
      placeholder vermelho na página e é **fatal** no boot em produção.
      Decisões suas que estão como default no rascunho: janela de reembolso
      (`REFUND_WINDOW_DAYS=14`, mínimo que a lei da UE impõe de qualquer jeito),
      teto de responsabilidade em 12 meses de pagamento, idade mínima 16.
      **Não é parecer jurídico** — é um rascunho consistente com o que o código
      faz, pra você revisar (ou passar num advogado) antes de publicar.
- [ ] Submeter a conta Paddle para aprovação de produção

## Bloco 2 — enquanto a Paddle revisa

### Contas
- [ ] Verificar domínio no Resend (SPF/DKIM/DMARC) e ajustar `email_from`
      Hoje é `no-reply@example.com`. Sem domínio verificado o Resend recusa o
      envio, e `app/services/email.py:39-40` engole a falha em log porque roda em
      BackgroundTask — ou seja, **recuperação de senha morre em silêncio**.
      Desde 2026-08-01 os dois são **fatais** no boot, não avisos: o modo de
      falha (todo mundo que esquece a senha fica trancado, e você descobre por
      ticket) é caro demais para subir com ele.
      **Subiu de importância em 2026-08-05:** com a verificação de email, o
      bônus de 8 créditos só é pago na confirmação. Email quebrado agora não
      tranca só quem esqueceu a senha — deixa **todo cadastro novo com saldo
      zero**, no dia do lançamento, sem erro em lugar nenhum.
      **Virou o item mais crítico do bloco em 2026-08-18:** com o gate duro,
      confirmar o endereço é pré-requisito pra upload E pra pagamento. Resend
      quebrado agora não é um funil pior — é **funil zero**: ninguém sobe uma
      imagem, ninguém assina, e o app não erra em lugar nenhum porque o envio
      falha dentro de uma BackgroundTask. Some com o produto inteiro atrás de
      um link que nunca chega. É a primeira coisa a testar de ponta a ponta no
      domínio novo (cadastrar, receber, clicar), antes de qualquer divulgação.
- [ ] Trocar os price IDs de sandbox pelos de produção
      `PADDLE_PRICE_BASIC` / `PADDLE_PRICE_PRO` no .env (antes eram hardcoded
      em `app/services/billing.py`). Também **fatal** desde 2026-08-01: os ids
      de sandbox são o default, e `PADDLE_ENVIRONMENT=production` sozinho não
      contradizia eles — passava em tudo e todo checkout ia ao ar sem cobrar.
      Lembre do `custom_data` de cada preço na Paddle:
      `{"app": "superscaler", "plan": "<slug>", "credits": <mensalidade>}` —
      é dele que sai a mensalidade real (`plan_in_transaction`).
- [ ] Registrar o webhook da Paddle na URL pública nova
- [ ] `paddle_environment=production`

### Servidor
- [x] ~~**Rescale CX22 → CX32**~~ RESOLVIDO DE OUTRO JEITO 2026-08-05: o usuário
      contratou uma máquina nova de 8 GB **para todos os projetos** (Next.js
      atual + mais um + dois projetos Python + este). Não há rescale nem
      downtime dos outros projetos — há uma migração para a caixa nova.
      Servidor dedicado foi cogitado e **recusado** (custo, ~€5/mês, sem receita
      ainda). Consequências, todas já aplicadas no compose:
      `max_concurrent_jobs=1`, `mem_limit: 3.5g`, `cpus: 2.0`.
      Medido em 2026-08-05 na imagem real: **100 MB em repouso**; os ~3 GB são
      um pico de 60–90s por job. Orçamento da caixa: ~1,7 GB de base para os
      cinco projetos + SO, ~3,5 GB de teto para um job daqui, sobra folga.
      **Pendente de decisão de arquitetura:** um proxy só para os cinco apps
      (só um processo pode segurar 80/443) — ver `deploy/README.md`.
      **Pendente de higiene:** `mem_limit` nos OUTROS projetos também, senão
      quem escolhe a vítima do OOM é o kernel, e ele costuma escolher o maior
      processo, que pode ser um inocente.
- [x] Dockerfile + docker-compose (com `mem_limit` e `restart: always`)
      FEITO 2026-08-05. `Dockerfile` (multi-stage com uv, venv do lock, usuário
      não-root, HEALTHCHECK no `/health`), `.dockerignore`, `docker-compose.yml`
      (app + Caddy, volumes nomeados, `depends_on: service_healthy`),
      `deploy/README.md` com a ordem de operações. **Imagem construída e
      testada**: sobe, migra, serve `/`, `/health` e `/static`, e com
      `ENVIRONMENT=production` recusa subir listando os 11 problemas.
      `mem_limit: 6g` porque o que tem que caber é `max_concurrent_jobs` × pico
      (~3 GB), não o pico de um job — é essa multiplicação que amarra o
      `max_concurrent_jobs=2` ao item do bloco 4.
      Atenção: `/srv` é do root dentro do container, só `/srv/storage` é
      gravável pelo processo. Em produção o storage é R2, então isso só
      importa se você voltar pro disco local.
- [x] Caddy: TLS automático + **sobrescrever** `X-Forwarded-For`
      FEITO 2026-08-05: `deploy/Caddyfile` (validado com `caddy validate`).
      Correção de uma premissa antiga desta lista: **o Caddy ≥2.7 não acrescenta
      ao header do cliente** — ele descarta o `X-Forwarded-For` de origem não
      confiável. Medido no `caddy:2.10-alpine`, forjando `1.2.3.4`: default
      entrega `10.0.2.1` (forja some), com `trusted_proxies 0.0.0.0/0` entrega
      `1.2.3.4, 10.0.2.1` (forja passa, e `app/api/ratelimit.py:16` lê o
      PRIMEIRO). O `header_up X-Forwarded-For {remote_host}` está lá assim
      mesmo: é redundante hoje e deixa de ser no dia em que alguém puser
      `trusted_proxies` pra botar Cloudflare na frente. Quem usa nginx é que
      precisa mesmo: `proxy_set_header X-Forwarded-For $remote_addr;`
- [ ] **`ENVIRONMENT=production` no .env** — sem isso a validação de boot
      (bloco Código) fica MUDA e todo o resto desta lista volta a ser silencioso.
      Ponha primeiro: com ela ligada o app recusa subir e diz o que falta.
- [ ] `trust_proxy_headers=True`
- [ ] `cookie_secure=True`
- [x] `workers=1` explícito
      FEITO: está no `CMD` do `Dockerfile` (`uvicorn ... --workers 1`), não no
      compose — o compose não sobrescreve `command`, então vale de qualquer
      jeito, e no Dockerfile vale também pra quem rodar a imagem na mão.
      (`run_migrations()` roda no import em `app/main.py:22` e correria com N workers.)
- [x] `max_concurrent_jobs` — **1** (não 2), já no `docker-compose.yml` junto com
      `cookie_secure` e `trust_proxy_headers`. Caixa compartilhada: ver o item do
      servidor acima. Volta a 2 quando o pico de memória do pós-processamento
      cair (bloco 4).
      Desde 2026-08-05 esse número é o `max_workers` do pool de jobs
      (`app/jobs/queue.py`), não mais um semáforo dentro do worker — a diferença
      importa e está no item do threadpool, no bloco 3.
- [ ] Hetzner Cloud Firewall: 80/443 abertos, SSH restrito ao seu IP
- [x] systemd para o compose
      FEITO 2026-08-05: `deploy/superscaler.service` (oneshot + RemainAfterExit,
      `docker compose up -d --build`). Só instalar e habilitar no servidor.
- [ ] Swap 4–8 GB (rede de segurança; menos urgente com 8 GB)

### Código
- [x] `[código]` Validação de config no boot
      FEITO 2026-08-01. Hoje o app subia silenciosamente errado.
      `config_problems()` em `app/core/config.py`, chamada no import de
      `main.py` ANTES das migrações — só age com `ENVIRONMENT=production`,
      porque os defaults de dev são exatamente os valores "errados".
      **Fatais** (recusa subir, e lista TODOS de uma vez em vez de um restart
      por erro): token da Replicate vazio, `paddle_webhook_secret` vazio,
      `paddle_api_key` vazio, `paddle_client_token` vazio, `paddle_environment`
      ainda em sandbox, `cookie_secure=False`, `app_base_url` sem https ou com
      localhost, `database_url` ainda em SQLite.
      **Avisos** (loga e sobe): rate limit desligado, `trust_proxy_headers=False`
      (atrás do Caddy todo cliente vira um IP só e o limite por IP estrangula
      todo mundo junto), sem bucket R2. Isso cobre boa parte do checklist de
      `.env` acima — o deploy erra alto e cedo em vez de silencioso.

      **Estendida 2026-08-01** (review de segurança), dois furos no caminho do
      dinheiro e do login que passavam por todos os checks:
      - `PADDLE_PRICE_BASIC` / `PADDLE_PRICE_PRO` vazios ou **ainda iguais aos
        de sandbox** → fatal. Os ids agora vêm da config; antes eram hardcoded
        e o guard não olhava para eles. Detecção por comparação com as
        constantes `SANDBOX_PRICE_*`, não por prefixo: na Paddle Billing os ids
        são `pri_01...` nos dois ambientes e **nada na string diz qual é qual**.
      - `RESEND_API_KEY` vazio e `EMAIL_FROM` em example.com passaram de aviso
        a fatal (ver bloco Contas).
      Testes: 5 casos novos em `test_each_silent_failure_is_fatal` mais
      `test_the_sandbox_defaults_are_what_a_forgotten_swap_looks_like` (o erro
      realista: config toda live, ninguém tocou nos `PADDLE_PRICE_*`).
      Testes: `tests/test_config_checks.py` (17).
- [x] `[código]` Timeout no polling da Replicate
      FEITO 2026-08-01. O `while pred["status"] in ("starting","processing")`
      não tinha prazo; um job preso segurava o slot pra sempre e travava a fila
      de todos. Agora `prediction_timeout_seconds` (default 600 — generoso: um
      modelo frio na Replicate leva minutos pra subir antes dos ~60s de GPU) e,
      ao estourar, CANCELA a predição (parar de pagar GPU que não vamos usar,
      best effort — cancel que falha não pode mascarar o timeout) e levanta
      RuntimeError, que o worker já traduz em job `failed` + refund.
      Testes: `tests/test_provider_timeout.py` (4).
- [ ] Sentry — não bloqueia o lançamento: `logging.basicConfig(INFO)` manda
      tudo pro stdout e o systemd guarda no journalctl (`journalctl -fu ...`).
      Vale no dia em que houver usuário pagante que você não conhece.

### Código — sangram dinheiro, fechar antes da primeira cobrança real

- [x] `[código]` `[pag]` **Fallback por `subscription_id` no webhook de renovação**
      FEITO 2026-08-01. Era: `app/api/billing.py` descartava o evento se
      `data.custom_data.app` não batesse, e achava o usuário por
      `custom_data.user_id` — o que você injeta **no checkout**. Se a Paddle não
      propagar esse `custom_data` para as transações de renovação, TODA renovação
      virava `{"status": "ignored"}` e o cliente pagante não recebia crédito, em
      silêncio, com log nível warning.
      Correção: o gate de `custom_data` saiu do endpoint — cada handler decide
      posse por algo durável. `_handle_transaction_completed` checa primeiro a
      tag do PREÇO nos line items (`plan_in_transaction`, que a Paddle carrega em
      toda transação da assinatura) e, se o `user_id` não resolver, acha o dono
      por `User.paddle_subscription_id == subscription_id` (ids de assinatura são
      únicos na Paddle, então evento de outro app continua sem casar).
      `subscription.canceled` ganhou a mesma proteção de graça — antes dependia do
      mesmo `custom_data` e falharia em silêncio no sentido oposto (assinatura
      cancelada que continua dando créditos).
      Testes: `test_renewal_finds_user_by_subscription_when_custom_data_is_missing`
      e `test_renewal_of_an_untracked_subscription_is_ignored`.
      **Ainda vale confirmar com uma renovação real no sandbox.**

- [x] `[código]` `[pag]` **Prorratear a concessão de créditos no upgrade**
      FEITO 2026-08-01. Era: a cobrança do upgrade é prorrateada, a concessão
      não — `apply_renewal` fazia `user.credits = credits`, mensalidade cheia,
      não importa quantos dias sobraram. Arbitragem, sem habilidade nenhuma, só
      clicando na hora certa:
        1. Assina Basic — $12, 250 créditos
        2. Dia 29 de 30, upgrade pro Pro → proração cobra ~$0,90 → reseta pra 1000
        3. Downgrade imediato pro Basic → agenda pro próximo ciclo, não cobra
        4. Repete todo mês
      **$12,90/mês por 1000 créditos que custam $39.**
      Correção: `billing.proration_rate(data)` mede que fração do período a
      cobrança comprou — `proration.rate` do line item quando a Paddle manda,
      senão a janela do `billing_period` (denominador 30 dias; período ≥27,5 dias
      = período cheio, para renovação de fevereiro não virar proração), senão 0
      quando o `origin` é `subscription_update` e não dá pra medir (não concede
      nada agora; a próxima renovação liquida a cota cheia). Com taxa, o
      `apply_renewal` concede só a DIFERENÇA de cota vezes a taxa, SOMADA ao saldo
      (os créditos do plano atual já estão lá), razão `plan_upgrade` no ledger.
      O caso do exploit vira 25 créditos em vez de 1000.
      Testes: `test_last_day_upgrade_is_not_an_arbitrage` + 5 outros na seção
      "prorated plan changes". Copy do modal de upgrade atualizada junto
      (`billing.js`), senão o usuário legítimo esperaria a cota cheia na hora.
      **RESSALVA — validar no sandbox antes de cobrar de verdade:** os payloads
      dos testes foram montados a partir da documentação da Paddle, não de um
      upgrade real observado. O caminho principal (`proration.rate` no line
      item) é o documentado; os dois fallbacks existem exatamente porque a forma
      real nunca foi vista. Um upgrade de verdade no sandbox mostra qual caminho
      dispara — o log do webhook agora imprime `prorated 0.xxx` quando prorrateia,
      então dá pra conferir sem depurar. Mesma sessão de teste confirma a
      renovação do item acima.

- [x] `[código]` `[seg]` **DoS de upload — corpo inteiro na RAM antes da checagem**
      FEITO 2026-08-01. Era: `data = await file.read()` lia tudo e SÓ DEPOIS
      comparava com `max_upload_mb`. O Starlette faz spool pra disco acima de
      1 MB, então um upload de 5 GB primeiro enchia o disco e depois ia pra
      memória. Na máquina que estamos dimensionando, mata o processo.
      Correção: `app/api/body_limit.py`, middleware ASGI puro registrado como o
      mais externo em `main.py` — tinha que ser antes do roteamento, porque
      quando o endpoint enxerga o `UploadFile` o FastAPI JÁ parseou o multipart
      inteiro (checar `Content-Length` dentro da rota seria tarde demais).
      Recusa pelo `Content-Length` quando ele existe (caso normal, e o único
      jeito de recusar sem ler nada) e CONTA os bytes chegando quando não existe
      — requisição chunked não declara tamanho e cliente hostil mente. Teto =
      `max_upload_mb` + 64 KB de folga pro envelope multipart, lido do settings a
      cada request (muda com o .env, sem restart de config). O limite exato do
      arquivo continua no endpoint, agora com leitura em blocos de 256 KB.
      Vale como defesa em profundidade junto com o `max_request_body_size` do
      Caddy (bloco 4) — o proxy protege a rede, isso protege o processo.
      Testes: `tests/test_body_limit.py` (5).

- [x] `[código]` `[seg]` **Enumeração de usuários por timing no login**
      FEITO 2026-08-01. Era: email inexistente retornava na hora, email
      existente rodava o Argon2 — **62 ms de diferença, medido**, anulando o
      cuidado de devolver a mesma mensagem nos dois casos.
      Correção: `_DUMMY_HASH` em `app/auth/service.py` (hash de um token
      aleatório, gerado uma vez no import) e `verify_password` passou a aceitar
      `password_hash=None` = "não existe usuário", verificando contra o dummy —
      os parâmetros de custo do Argon2 vão dentro da string do hash, então
      custa exatamente o mesmo de uma verificação real. O router chama sempre,
      sem curto-circuito.
      Medido depois, 15 pares intercalados: 68,8 ms (senha errada) × 67,9 ms
      (email inexistente) = **-0,9 ms**, dentro do ruído.
      Testes: `test_unknown_email_still_costs_a_password_verification` (prova
      que a verificação acontece, sem depender de relógio) e
      `test_verify_password_without_a_user_is_false`.

---

## Bloco 3 — adiado conscientemente (não é esquecimento)

Cada um destes tem um gatilho. Enquanto o gatilho não vier, dá pra viver sem.

- [x] `[código]` **Verificação de email no cadastro**
      FEITO 2026-08-05 (antecipado: o gatilho era abuso, mas o item de baixo
      obrigou a mexer no mesmo caminho, e o custo caiu junto).
      Era: `register` creditava os 8 créditos sem confirmar nada = dinheiro de
      GPU por email descartável.
      Correção, e o detalhe que importa: **o cadastro não mudou de forma, o
      BÔNUS é que mudou de hora**. `register` cria o usuário com `credits=0`,
      loga a pessoa normalmente e manda o link; `service.grant_signup_bonus`
      lança os 8 créditos no ledger quando o endereço é confirmado, uma vez só
      (`if user.email_verified_at is not None: return`). Conta não confirmada
      navegava, subia imagem e até assinava — só não ganhava crédito de graça,
      para evitar o modo de falha clássico ("confirme para usar" + email que
      não chega = funil zerado no dia do lançamento).
      **REVISTO EM 2026-08-18 (ver a atualização no topo):** o gate ficou duro
      a pedido do usuário. Upload e pagamento agora exigem confirmação, e o
      dashboard nem carrega — `/verify` virou sala de espera. Pela API sobrou
      só cancelar assinatura. O modo de falha que este parágrafo evitava
      passou a ser aceito conscientemente — e é exatamente por isso que o item
      do Resend, no bloco 2, virou o mais crítico da lista.
      `POST /auth/verify` consome o link e **também loga** (o link é aberto num
      navegador diferente do que cadastrou, rotineiramente);
      `POST /auth/resend-verification` reemite, com limite próprio
      (`verify_resend_rate_limit`, 3/h por usuário — cada hit é email real).
      TTL de 24h (`email_verification_ttl_hours`): link de confirmação espera
      alguém abrir a caixa de entrada, diferente do reset que a pessoa pediu há
      um minuto. Expirar não é beco sem saída, o reenvio existe.
      Migração `87f3143089b7`; página `/verify` (`verify.html`) + faixa no
      `base.html` pra conta não confirmada.
      Testes: `tests/test_email_verification.py` (11).
      **Consequência pro `.env`:** `RESEND_API_KEY` e `EMAIL_FROM` ficaram ainda
      mais fatais — agora seguram o bônus de todo cadastro novo, não só a
      recuperação de senha. A mensagem do `config_problems` já diz isso.
- [ ] `[código]` **Tratar `past_due` da Paddle**
      O webhook só trata `transaction.completed` e `subscription.canceled`.
      Assinatura inadimplente segue com plano ativo até a Paddle cancelar sozinha.
      *Gatilho: primeiro pagamento recorrente falhar — semanas depois do lançamento.*
- [ ] `[código]` **Retry de job** (está nos requisitos do SPEC)
      5xx transiente da Replicate mata o job. O crédito é estornado, então o
      prejuízo é de experiência, não de dinheiro. *Gatilho: reclamação ou taxa de
      falha visível no Sentry.*
- [x] `[código]` **Threadpool: jobs em espera seguram threads do anyio**
      FEITO 2026-08-05 (antecipado: o gatilho era "40 jobs simultâneos", mas o
      caminho até lá custava 1 crédito por job e nada limitava o `POST /jobs` —
      barato demais pra deixar de pé).
      Era: `BackgroundTasks` entrega a função síncrona ao threadpool do
      Starlette — o MESMO pool de 40 slots (CapacityLimiter do anyio) que serve
      toda rota `def` do app. Um job segura sua thread pelos 30-90s inteiros,
      então 40 jobs em voo deixavam zero threads pro HTTP: login, download,
      webhook da Paddle e até `/health` paravam de responder até a fila drenar.
      Correção, em `app/jobs/queue.py`: pool próprio
      (`ThreadPoolExecutor(max_workers=max_concurrent_jobs)`). A fila espera em
      threads dela, e o caminho de request nunca é faminto. O semáforo dentro do
      worker SAIU — era justamente ele que fazia job em espera segurar thread
      alheia; o teto de concorrência agora é o `max_workers` do pool.
      Junto vieram os dois tetos que faltavam (não estavam nesta lista):
      `max_queued_jobs` (20, global → **503**, "todo mundo está esperando") e
      `max_queued_jobs_per_user` (3 → **429**, "você já tem vários rodando"),
      porque só o teto global é monopolizável por uma conta. `queue.reserve()` é
      chamado ANTES da linha do job e do débito — job que a fila recusaria não
      pode custar crédito de ninguém —, e `release()` devolve a vaga em qualquer
      saída, inclusive exceção. Nada disso sobrevive a restart, e não precisa:
      `app/main.py` falha e estorna todo job "queued"/"running" no boot.
      Testes: `tests/test_worker_concurrency.py` (10).
- [ ] Drain gracioso no deploy (parar de aceitar jobs → esperar slots → reiniciar)
      Sem isso todo deploy mata os jobs em voo. O `main.py:22-35` estorna os
      créditos no boot seguinte, mas o usuário perde o resultado.
      *Gatilho: deixar de conseguir fazer deploy em horário vazio.*
- [ ] Dump próprio do Neon pro R2
      O Neon tem backup gerenciado; o dump seu é o que salva de erro **seu**.
      *Gatilho: antes da primeira migração destrutiva.*
- [ ] Uptime check externo

- [ ] `[código]` `[pag]` **Reembolso e chargeback não existem no código**
      Só `transaction.completed` e `subscription.canceled` são tratados.
      Cliente compra 1000 créditos, gasta tudo, pede reembolso na Paddle — nada
      acontece do seu lado. `adjustment.created` / `transaction.updated` não
      chegam a lugar nenhum. *Gatilho: primeiro pedido de reembolso.*

- [x] `[código]` `[pag]` **Downgrade agendado e cancelamento prendem o usuário**
      FEITO 2026-08-01 (antecipado: o gatilho era "primeiro ticket de suporte",
      e o custo era 1h).
      Era: agendou downgrade Pro→Basic (`plan_pending`) e mudou de ideia? Batia
      em `if target.slug == user.plan` → 400 "already on this plan", porque
      `user.plan` ainda é "pro". Cancelou sem querer? Com `plan_cancels_at`
      setado o `change_plan` recusava tudo e não existia endpoint de retomar —
      só esperar expirar e assinar de novo.
      Correção, dois caminhos de volta:
      - `POST /billing/resume` → `billing.resume_subscription()` faz
        `PATCH /subscriptions/{id}` com `scheduled_change: null`. Nada é cobrado
        (o período corrente já foi pago) e a próxima renovação volta a ser
        renovação normal. Idempotente: sem cancelamento agendado não chama a
        Paddle. Erro da Paddle = 502 e o agendamento continua de pé.
      - `change_plan` com o plano ATUAL e `plan_pending` setado deixou de ser 400
        e virou "never mind": PATCH dos items de volta pro preço atual com
        `full_next_billing_period` (não cobra nada agora, renova no plano atual),
        limpa `plan_pending`, responde `{"status": "kept"}`. Sem `plan_pending`,
        continua 400 "already on this plan".
      Bloqueio de troca durante cancelamento agendado foi MANTIDO de propósito
      (a Paddle recusaria mesmo) — a mensagem agora aponta o caminho: "resume it
      first".
      UI (`billing.js`): o botão de cancelar vira **"Resume subscription"**
      quando há cancelamento agendado, em UM clique (o duplo-clique protege ação
      destrutiva; desfazer engano não precisa de convencimento), e o botão do
      plano atual vira **"Keep {plano}"** quando há downgrade agendado.
      Testes: 6 na seção "changing your mind" de `tests/test_billing.py`.

- [x] `[código]` `[seg]` **`error_message` cru devolvido ao usuário**
      FEITO 2026-08-05 (antecipado: o gatilho era o Sentry, mas o conserto é uma
      linha e não depende dele).
      Era: `str(exc)` de qualquer exceção do pipeline ia pro cliente via
      `GET /jobs/{id}` — caminhos internos, URLs de predição da Replicate, corpo
      de erro da API.
      Correção: `app/workers/enhance.py:55` grava a frase fixa
      `"The enhancement failed."`, e o `logger.exception` logo acima é quem
      guarda tudo (traceback inteiro no journalctl). Quando o Sentry entrar, ele
      lê o mesmo log — nada a refazer aqui.

- [x] `[seg]` **Cabeçalhos de segurança** — FEITO 2026-08-05 no `deploy/Caddyfile`,
      junto com o Caddy, como previsto. Você serve imagem de usuário na mesma
      origem com Content-Type adivinhado por extensão; os formatos são validados
      pelo PIL (só JPEG/PNG/WEBP, sem SVG), então XSS armazenado é improvável —
      `nosniff` é a rede contra polyglot, e `frame-ancestors` fecha o
      clickjacking no fluxo de billing.
      **Enforcing:** `nosniff`, `X-Frame-Options: DENY`, HSTS 1 ano,
      `Referrer-Policy`, COOP `same-origin-allow-popups` (o `same-origin` puro
      quebra o popup de pagamento da Paddle) e um CSP curto com
      `frame-ancestors 'none'; base-uri 'self'; form-action 'self';
      object-src 'none'` — os quatro já são verdade hoje.
      **Report-Only:** o CSP com allowlist de script/style/connect/frame.
      Motivo de não estar enforcing: a página puxa Tailwind do jsDelivr, fontes
      do Google e Paddle.js, e nem "o build do Tailwind precisa de
      `unsafe-eval`?" nem "quais hosts `*.paddle.com` o checkout realmente
      chama?" se responde lendo o código. O checkout de sandbox que você já
      deve rodar responde os dois no console — aí é só renomear o header.
      Também no Caddy: `request_body max_size 26MB` (o teto exato continua no
      middleware do app, isso protege a rede antes).

- [ ] `[código]` `[seg]` **Sem cota de armazenamento por conta**
      20 uploads/min × 25 MB = ~30 GB/hora de R2 por conta grátis. Isso é dinheiro
      seu, não invasão. *Gatilho: primeira fatura do R2 fora do esperado.*
      **Encolheu, não fechou, em 2026-08-18:** o gate de upload exige endereço
      confirmado e saldo que cubra a imagem, então quem faz isso precisa de uma
      caixa de entrada real e de crédito no saldo. Mas upload **não debita** —
      com 8 créditos de bônus e nenhum job, os mesmos 30 GB/hora continuam
      possíveis. O que mudou é o custo do ataque, não o teto.

- [ ] `[código]` `[seg]` **Enumeração no cadastro** — `409 "email already
      registered"` (`app/auth/router.py:66`) contradiz o cuidado do login e do
      forgot. **A previsão desta linha estava errada:** a verificação de email
      entrou em 2026-08-05 e o 409 CONTINUA lá, porque o cadastro loga a pessoa
      na hora (decisão de funil, ver o item da verificação) — não dá pra
      responder "enviamos um email" e devolver uma sessão ao mesmo tempo.
      Fechar de verdade custa mudar o fluxo: cadastro deixa de logar e passa a
      responder sempre igual, com a sessão nascendo só no `/verify`. É pagar
      funil por privacidade de endereço. *Gatilho: alguém reclamar, ou o dia em
      que o cadastro deixar de logar por outro motivo.*

### Fechados sem estar na lista (2026-08-05)

Achados ao fechar os itens acima. Ficam registrados porque a lista é a memória
do projeto — item que não está escrito volta a ser "descoberto" daqui a um mês.

- [x] `[seg]` **Segredos no `repr` do `Settings`** — `replicate_api_token`,
      `paddle_api_key`, `paddle_webhook_secret`, `resend_api_key`,
      `r2_secret_access_key` e `database_url` (que carrega a senha do Neon)
      viraram `SecretStr`. O `repr` de um objeto de settings aparece onde
      ninguém planeja — diff de assert do pytest, exceção renderizada por
      framework, print de debug — e levava o token vivo junto. Desembrulha com
      `.get_secret_value()` no ponto de uso; f-string **não** desembrulha, ela
      mascara, então chamada esquecida falha alto em vez de vazar.
      `paddle_client_token` ficou de fora de propósito: ele é entregue ao
      navegador por `/billing/plans`, é pra isso que serve.
      `validate_assignment=True` no `model_config` porque testes atribuem string
      crua e o erro apareceria longe da atribuição.
- [x] `[seg]` **Download inteiro na RAM** — as três rotas de `/download` liam o
      arquivo todo antes de responder. Um PNG melhorado no `max_image_px` tem
      dezenas de MB, e a caixa está dimensionada pro pico de UM job, não pra
      downloads simultâneos. Agora `storage.stream()` (256 KB por bloco) nos dois
      backends, com `StreamingResponse`. Detalhe que custa um bug se for copiado
      errado: o arquivo é aberto **fora** do gerador — corpo de gerador só roda
      no primeiro chunk puxado, quando a resposta já começou e um arquivo
      faltando não pode mais virar 404. O `get_object` do S3 já resolve na hora,
      mesmo contrato. Testes: `tests/test_storage.py` (7).
- [x] `[seg]` **Upload malformado virava 500** — `image.verify()` só tinha
      `UnidentifiedImageError` no `except`. PNG truncado levanta `OSError` puro,
      e header quebrado sai como `ValueError`/`SyntaxError`: todos eram 500 numa
      requisição que qualquer um faz de graça. Agora os quatro dão 415, e
      `DecompressionBombError` (um PNG de 227 KB pode declarar 20000×12000, e o
      PIL recusa antes de decodificar) dá **413** — a mesma resposta do
      `max_image_px`, que é onde ele ia falhar de qualquer jeito.
- [x] `[seg]` **Tetos de fila** — descrito no item do threadpool acima
      (`max_queued_jobs`, `max_queued_jobs_per_user`). Repetido aqui só porque
      não é consequência do bug do threadpool: sem eles, nada limitava quantos
      jobs uma conta podia empilhar.

## Antes de divulgar publicamente

Nada aberto aqui desde 2026-08-01 — o único item da seção está feito.

- [x] `[código]` `[pag]` **Exclusão de conta**
      FEITO 2026-08-01. `POST /auth/delete` + `app/services/account.py` +
      modal "Account" na sidebar (`account.js`).
      Os três problemas, e como cada um foi resolvido:
      - **Legal** (UE, direito ao apagamento): agora é self-service. **A política
        de privacidade pode prometer o botão** — antes o texto teria que
        descrever processo manual por email.
      - **Financeiro:** cancela na Paddle ANTES de qualquer coisa e com
        `effective_from: immediately` (conta que ninguém consegue logar não pode
        seguir sendo cobrada; `cancel_subscription` ganhou o parâmetro
        `immediately`). Falha da Paddle = 502 e **nada é commitado** — apagar
        local com o cartão rodando é o pior desfecho possível, tem teste.
      - **Estrutural:** a linha de `users` SOBREVIVE, esfregada. `payments` é
        retido por obrigação fiscal e `credit_ledger` é histórico append-only, e
        os dois têm FK pra `users.id` — cascata levaria a contabilidade junto.
        Some: imagens (+ arquivos no storage, depois do commit), jobs (com o
        `job_id` do ledger anulado antes, mesma regra do DELETE /images),
        sessões e tokens de reset. Fica: email trocado por
        `deleted+{id}@deleted.invalid` (RFC 2606 — libera o endereço pra pessoa
        se cadastrar de novo), `password_hash` vazio, saldo zerado COM lançamento
        `account_deleted` no ledger (saldo e ledger nunca divergem), `deleted_at`
        setado (migração `9cac42c7b507`).
      Exige a senha atual: sessão roubada não destrói biblioteca e assinatura.
      `user_from_token` passou a recusar usuário com `deleted_at` — a exclusão
      já apaga todas as sessões, isso é a segunda tranca.
      Testes: `tests/test_account_delete.py` (8).

---

## Bloco 4 — dívida técnica conhecida

- [ ] Memória do `color_match` (`app/pipeline/stages/post_processor.py`)
      ADIADO 2026-07-29 em favor do CX32 — adiado, não descartado.
      `_decompose` mantém `high`, `low`, `blurred` e o temporário de
      `high += low - blurred` vivos ao mesmo tempo. O pico está inteiro aí —
      o RSS não sobe depois dele. Reescrever in-place e por faixas horizontais
      derruba de ~3 GB para ~400 MB e acelera todo job. Meio dia + testes de
      regressão numérica.
      Não afeta qualidade: os suportes das 5 convoluções somam 248 px
      (4×(2+4+8+16+32)), então faixas de largura total com 256 px de halo dão
      resultado idêntico BIT A BIT, e o teste de regressão exige diferença
      máxima 0 rodando em CPU contra `validation/outputs/` — US$0 de GPU,
      zero recalibração. *Gatilho: querer voltar pra 4 GB, ou subir
      `max_image_px` (o pico cresce com o quadrado dele).*

      **Revisado 2026-08-05, lendo o arquivo de novo — duas correções:**
      1. O `sharpen()` também aloca ~7 buffers do tamanho da imagem (`blurred`,
         `gray`, `grad`, `gate`, `sharpened`, `lo`, `hi`), ~340 MB cada na saída
         máxima. Consertar só o `_decompose` provavelmente NÃO entrega os
         400 MB — o pico desce até o segundo maior consumidor. A mesma técnica
         serve (halo de ~8 px lá, contra 256 aqui), mas a estimativa vira ~1 dia,
         não meio. **Medir o pico por estágio antes de mexer** — uma hora, e
         evita otimizar por suposição.
      2. "BIT A BIT" é a meta e o critério do teste, não uma garantia dada de
         antemão: o argumento (cada pixel depende só da vizinhança de 248 px,
         sem acumulação entre pixels) é sólido, mas resta o arredondamento do
         OpenCV em buffers de forma diferente. Se aparecer diferença de 1/255
         na borda das faixas, isso é decisão do usuário, não afrouxamento
         silencioso do teste.

      *Gatilho novo (2026-08-05): a caixa de 8 GB é compartilhada com 4 outros
      projetos, então `max_concurrent_jobs` está em 1. Este item é o que
      devolve o 2 — não bloqueia o lançamento, mas é o teto de throughput.*
- [ ] Redis/RQ — só quando precisar da segunda instância.
      Ponto de troca já isolado em `app/jobs/queue.py`.

- [ ] `[pag]` **`users.credits` é balde único sem proveniência** — decisão de
      arquitetura, precisa de aval antes de mexer.
      `apply_renewal` sobrescreve o saldo inteiro; `expire_subscription` zera o
      saldo inteiro. Hoje isso só significa que os 8 créditos de boas-vindas somem
      na primeira compra (250, não 258) — irrelevante. Mas no dia em que existir
      pacote avulso de créditos, **cancelar a assinatura destrói crédito comprado
      à parte**. Barato agora, caro depois.

- [x] `[pag]` **`apply_renewal` apaga o vínculo da assinatura sem checar nulo**
      FEITO 2026-08-01 (subiu de prioridade: virou dependência da correção do
      webhook do bloco 2 — o fallback que acha o dono de uma renovação sem
      `custom_data` procura exatamente por esse campo, então zerá-lo reabria o
      furo de renovação silenciosamente descartada).
      Era: `user.paddle_subscription_id = subscription_id` incondicional — uma
      transação avulsa marcada com o seu `custom_data` chega com
      `subscription_id = None` e zerava o vínculo; o usuário perdia cancelar e
      trocar de plano ("no active subscription") com a assinatura viva na
      Paddle. Agora só sobrescreve quando vem valor; quem limpa o vínculo
      continua sendo o `expire_subscription`.
      Teste: `test_transaction_without_a_subscription_keeps_the_link`.

- [x] `[seg]` **`LocalStorage._path` aceita caminho absoluto e `../`**
      FEITO 2026-08-05. Era: `return p if p.exists() else self.base / key` — uma
      chave apontando pra fora do base era lida, e o `delete()` usava o mesmo
      caminho. Não era explorável (toda chave é gerada pelo servidor: uuid4 em
      `images.py`, `job.id` em `exporter.py`), era mina terrestre.
      Correção: chave absoluta e `../` que escapa do base levantam
      `FileNotFoundError` (`resolve()` + `is_relative_to`), e o prefixo legado
      `storage/` passou a ser removido explicitamente em vez de depender de
      "existe no disco?". O `put()` também usa `_path` agora — antes só o `get`
      normalizava, então gravação e leitura podiam divergir.

- [ ] `[seg]` **CSRF depende inteiramente de `SameSite=Lax`** — está correto hoje
      (nenhum endpoint que muda estado é GET), mas é ponto único: trocar pra
      `SameSite=None` (pra embutir em iframe, por exemplo) abre tudo de uma vez.
      Documentar a dependência conta como mitigação.

---

## O que as reviews confirmaram que está certo

Não mexer sem motivo forte — isto foi auditado e passou:

- **Webhook da Paddle:** HMAC-SHA256 sobre `ts:body`, `compare_digest` de tempo
  constante, janela de replay de 300s nos dois sentidos, múltiplos `h1` pra
  rotação de segredo.
- **Idempotência de pagamento:** constraint unique em `provider_transaction_id`
  + tratamento de `IntegrityError` na entrega concorrente.
- **Débito de crédito:** UPDATE condicional (`WHERE credits >= cost`) — imune a
  corrida, não dá pra gastar o mesmo crédito duas vezes.
- **Sessões e reset de senha:** 32 bytes de `secrets`, só o SHA-256 no banco,
  reset de uso único que revoga todas as sessões.
- **IDOR:** checagem de dono em todos os endpoints de imagem, job e download —
  conferidos um por um.
- **XSS:** frontend usa `textContent` pra todo dado dinâmico, `innerHTML` só com
  template estático. Jinja com autoescape.
- **SQL injection:** ORM em tudo, zero SQL cru.
- **Enumeração no `forgot`:** resposta idêntica + email em background
  explicitamente pra não vazar por timing.
- **25 testes de billing** cobrindo entrega duplicada, corpo adulterado,
  timestamp velho, assinatura não rastreada não expirando plano alheio, e falha
  da API da Paddle deixando o estado local intacto.
