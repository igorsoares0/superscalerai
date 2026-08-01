# Checklist de lançamento

Levantado em 2026-07-27, incluindo uma review de segurança e uma review do fluxo
de pagamentos. Atualizado em 2026-08-01. Estado do produto: **165 testes
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

Servidor: Hetzner. **Mínimo 8 GB de RAM** — o `post_processor` consome ~100 MB
por megapixel de saída (medido), e o pior caso permitido hoje (`max_image_px=3072`,
saída 6144×4608) tem pico de ~3,0 GB num único job. Numa máquina de 4 GB isso
encosta no teto mesmo com `max_concurrent_jobs=1`, e o OOM killer derruba o
uvicorn inteiro, não só o job.

**Decidido 2026-07-29: rescale do CX22 (4 GB) para o CX32 (8 GB)**, ~€1,80/mês a
mais, em vez de otimizar o `color_match` (que fica adiado no bloco 4). O servidor
hospeda outros projetos do usuário, então o `mem_limit` do compose deixa de ser
higiene e vira isolamento: sem ele, um OOM deste app derruba os outros junto.

---

## Bloco 1 — começar HOJE (é fila de terceiro, não trabalho seu)

A aprovação da Paddle é o único item que depende de outra pessoa e pode levar
dias. Tudo no bloco 2 cabe dentro dessa espera.

- [ ] Registrar domínio + apontar DNS
- [ ] Páginas de termos, privacidade e política de reembolso
      (a Paddle costuma exigir as três na revisão — pré-requisito do item abaixo)
- [ ] Submeter a conta Paddle para aprovação de produção

## Bloco 2 — enquanto a Paddle revisa

### Contas
- [ ] Verificar domínio no Resend (SPF/DKIM/DMARC) e ajustar `email_from`
      Hoje é `no-reply@example.com`. Sem domínio verificado o Resend recusa o
      envio, e `app/services/email.py:38` engole a falha em log porque roda em
      BackgroundTask — ou seja, **recuperação de senha morre em silêncio**.
- [ ] Trocar os price IDs de sandbox pelos de produção
- [ ] Registrar o webhook da Paddle na URL pública nova
- [ ] `paddle_environment=production`

### Servidor
- [ ] **Rescale CX22 → CX32** (desligar o servidor; escolher a opção que NÃO
      cresce o disco, senão o downgrade fica bloqueado pra sempre). Derruba os
      outros projetos por alguns minutos — agendar. Snapshot antes.
- [ ] Dockerfile + docker-compose (com `mem_limit` e `restart: always`)
- [ ] Caddy: TLS automático + **sobrescrever** `X-Forwarded-For`
      Atenção: `app/api/ratelimit.py:16` lê o PRIMEIRO IP da cadeia, e nginx/Caddy
      por padrão *acrescentam* ao header que o cliente mandou. Ligar
      `trust_proxy_headers=True` sem sobrescrever é pior que deixar desligado —
      qualquer um forja o header e fura todos os limites por IP.
      No nginx: `proxy_set_header X-Forwarded-For $remote_addr;`
- [ ] **`ENVIRONMENT=production` no .env** — sem isso a validação de boot
      (bloco Código) fica MUDA e todo o resto desta lista volta a ser silencioso.
      Ponha primeiro: com ela ligada o app recusa subir e diz o que falta.
- [ ] `trust_proxy_headers=True`
- [ ] `cookie_secure=True`
- [ ] `workers=1` explícito no compose
      (`run_migrations()` roda no import em `app/main.py:22` e correria com N workers)
- [ ] `max_concurrent_jobs=2` (default do código é 4 — explicitar no .env)
- [ ] Hetzner Cloud Firewall: 80/443 abertos, SSH restrito ao seu IP
- [ ] systemd para o compose
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
      todo mundo junto), sem bucket R2, sem `RESEND_API_KEY`, `EMAIL_FROM` ainda
      em example.com. Isso cobre boa parte do checklist de `.env` acima — o
      deploy erra alto e cedo em vez de silencioso.
      Testes: `tests/test_config_checks.py` (16).
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

- [ ] `[código]` **Verificação de email no cadastro**
      Hoje `register` credita os 8 créditos sem confirmar nada = dinheiro de GPU
      por email descartável. *Gatilho: primeiro sinal de abuso, ou passar de ~50
      cadastros/dia.* Até lá dá pra olhar a tabela de usuários na mão.
- [ ] `[código]` **Tratar `past_due` da Paddle**
      O webhook só trata `transaction.completed` e `subscription.canceled`.
      Assinatura inadimplente segue com plano ativo até a Paddle cancelar sozinha.
      *Gatilho: primeiro pagamento recorrente falhar — semanas depois do lançamento.*
- [ ] `[código]` **Retry de job** (está nos requisitos do SPEC)
      5xx transiente da Replicate mata o job. O crédito é estornado, então o
      prejuízo é de experiência, não de dinheiro. *Gatilho: reclamação ou taxa de
      falha visível no Sentry.*
- [ ] `[código]` **Threadpool: jobs em espera seguram threads do anyio**
      (`app/workers/enhance.py`) — o semáforo bloqueia dentro da thread, e o pool
      (limite 40) é o mesmo que serve as rotas síncronas. Fila cheia trava o site
      inteiro, sem erro e sem log. *Gatilho: 40 jobs simultâneos na fila — não
      acontece nos primeiros clientes.*
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

- [ ] `[código]` `[pag]` **Downgrade agendado e cancelamento prendem o usuário**
      Agendou downgrade Pro→Basic (`plan_pending`) e mudou de ideia? `change_plan`
      bate em `if target.slug == user.plan` → 400 "already on this plan", porque
      `user.plan` ainda é "pro". Não há caminho de volta.
      Mesma coisa no cancelamento: com `plan_cancels_at` setado, `change_plan`
      recusa tudo (`app/api/billing.py:66`) e **não existe endpoint de retomar**.
      Cancelou sem querer = suporte, ou esperar expirar e assinar de novo.
      *Gatilho: primeiro ticket de suporte — vai vir.*

- [ ] `[código]` `[seg]` **`error_message` cru devolvido ao usuário**
      `app/api/jobs.py:79` ← `app/workers/enhance.py:62`. `str(exc)` de qualquer
      exceção do pipeline vai pro cliente: caminhos internos, URLs de predição da
      Replicate, corpo de erro da API. Detalhe pro Sentry, genérico pro usuário.
      *Gatilho: assim que o Sentry estiver de pé.*

- [ ] `[seg]` **Cabeçalhos de segurança** — sem CSP, `X-Content-Type-Options:
      nosniff`, `frame-ancestors`, HSTS. Você serve imagem de usuário na mesma
      origem com Content-Type adivinhado por extensão. Os formatos são validados
      pelo PIL (só JPEG/PNG/WEBP, sem SVG), então XSS armazenado é improvável —
      mas `nosniff` é a rede contra polyglot, e sem `frame-ancestors` o fluxo de
      billing aceita clickjacking. *Gatilho: vai junto com o Caddy, é config.*

- [ ] `[código]` `[seg]` **Sem cota de armazenamento por conta**
      20 uploads/min × 25 MB = ~30 GB/hora de R2 por conta grátis. Isso é dinheiro
      seu, não invasão. *Gatilho: primeira fatura do R2 fora do esperado.*

- [ ] `[código]` `[seg]` **Enumeração no cadastro** — `409 "email already
      registered"` contradiz o cuidado do login e do forgot. Some sozinho quando
      a verificação de email entrar (resposta vira sempre "enviamos um email").

## Antes de divulgar publicamente

- [ ] `[código]` `[pag]` **Exclusão de conta — não existe**
      Três problemas empilhados:
      - **Legal:** hospedado na UE cobrando de europeus via Paddle. Direito ao
        apagamento não é opcional.
      - **Financeiro:** sem fluxo de exclusão não há código que cancele a
        assinatura na Paddle. Apagar o usuário direto no banco = **a cobrança
        continua** e o webhook passa a não achar dono (vira "ignored" num log).
        Cliente pagando por conta que não existe é o pior bug de billing possível.
      - **Estrutural:** `images`, `jobs`, `credit_ledger`, `payments`,
        `auth_sessions` e `password_resets` todos têm FK pra `users`. Delete
        simples quebra. E `payments` **precisa ser retido** por obrigação fiscal —
        o desenho correto é anonimizar a linha do usuário e preservar os
        pagamentos, não apagar em cascata.

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

- [ ] `[seg]` **`LocalStorage._path` aceita caminho absoluto e `../`**
      `app/services/storage.py:24-27`: `return p if p.exists() else self.base / key`.
      Chave apontando pra fora do base é lida — e o `delete()` usa o mesmo caminho.
      **Não é explorável hoje:** auditei todos os pontos de geração de chave e são
      todos do servidor (uuid4 em `images.py:53`, `job.id` em `exporter.py`). Em
      produção você usa S3Storage, que nem tem esse código. É mina terrestre.

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
