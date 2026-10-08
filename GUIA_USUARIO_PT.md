# Guia do Usuário

## Delphix Ruleset Drift Monitor

Esta ferramenta monitora a deriva estrutural entre um Ruleset produtivo do Delphix Continuous Compliance e um Ruleset de descoberta usado para identificar a estrutura atual do banco de dados de origem.

Seu objetivo é detectar alterações que possam deixar tabelas ou campos fora da cobertura de mascaramento.

## Fluxo de trabalho recomendado

Para adicionar um novo par de Rulesets:

1. Configure a conexão com o Delphix, o SMTP e as notificações.
2. Crie manualmente o Ruleset de descoberta no Delphix e alinhe inicialmente suas tabelas e campos com o Ruleset produtivo.
3. Consulte os Rulesets disponíveis no Engine com `--list-engine-rulesets`.
4. Registre o par produtivo/descoberta com `--add-ruleset`.
5. Crie a linha de base inicial com `--init-baseline`.
6. Execute a auditoria com `--audit`.
7. Analise as diferenças detectadas e corrija o Ruleset produtivo ou aceite explicitamente as diferenças.
8. Execute novamente `--init-baseline` depois de aplicar as correções.
9. Execute novamente `--audit` para confirmar que não restam diferenças sem tratamento.
10. Programe auditorias periódicas usando o timer do systemd.

Não reconstrua a linha de base automaticamente ao receber um alerta. Primeiro determine se a diferença exige cobertura de mascaramento ou se é uma alteração intencional que pode ser aceita.

## Casos monitorados

O monitor cobre estes cinco casos:

1. Tabelas adicionadas na origem.
2. Tabelas removidas da origem.
3. Campos adicionados a uma tabela.
4. Campos removidos de uma tabela.
5. Alterações de tipo de dado em campos existentes.

As alterações em tabelas conhecidas são avaliadas por meio de seus campos. Além disso, o monitor consulta o catálogo do conector do banco de dados de origem para detectar uma tabela que exista na origem, mas esteja ausente nos dois Rulesets. Se uma tabela aparecer com novas colunas, essas colunas serão informadas como novas; se todas as colunas conhecidas de uma tabela desaparecerem, serão informadas como removidas. O objetivo operacional é detectar qualquer alteração estrutural relevante.

## Conceitos principais

### Ruleset produtivo

É o Ruleset que contém a configuração aprovada de mascaramento: tabelas, campos e algoritmos.

### Ruleset de descoberta

É um Ruleset auxiliar atualizado contra o banco de dados de origem. Sua função é descobrir a estrutura real existente naquele momento.

### Linha de base

É o conjunto de diferenças conhecidas e aceitas entre os Rulesets produtivo e de descoberta. Uma diferença incluída na linha de base não gera um novo alerta durante a auditoria.

## Fluxo de uma auditoria

Para cada par ativo, o programa:

1. Consulta o inventário atual do Ruleset produtivo.
2. Armazena essa fotografia no SQLite.
3. Executa o refresh do Ruleset de descoberta.
4. Aguarda a conclusão da tarefa assíncrona do Delphix.
5. Consulta as tabelas e os campos descobertos pela sonda.
6. Consulta o catálogo do conector para obter as tabelas atualmente visíveis no banco de dados de origem.
7. Compara os dois inventários, o catálogo da origem e as exclusões da linha de base.
8. Exibe as diferenças.
9. Envia um e-mail HTML para cada Ruleset com diferenças, se o e-mail estiver habilitado.

## Instalação

O instalador identifica sua própria localização, portanto pode ser executado a partir de qualquer diretório:

```bash
sudo /caminho/para/o/repositorio/delphix-ruleset-monitor/install.sh
```

A instalação copia a aplicação para `/usr/local/bin/delphix-ruleset-monitor`, armazena os dados de execução em `/var/lib/delphix-ruleset-monitor`, cria o comando global `/usr/local/bin/ruleset_monitor.py` e habilita um timer do systemd que executa a auditoria de segunda a sexta-feira às 08:00.

Não é necessário executar `install_systemd.sh` depois de uma instalação completa. O `install.sh` já instala as unidades do systemd, recarrega o systemd e habilita o timer. Use `install_systemd.sh` somente quando a aplicação já estiver instalada e for necessário instalar ou atualizar as unidades do systemd de forma independente.

Cada instalação completa remove `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` se ela existir. Isso remove os pares registrados, os inventários produtivos e as exclusões da linha de base; portanto, será necessário registrar novamente os pares e criar suas linhas de base. A configuração em `/etc/delphix-ruleset-monitor/config.json` é preservada durante reinstalações.

### Separação entre aplicação e dados

A instalação mantém separados os scripts executáveis e os dados modificáveis:

| Finalidade | Localização |
|---|---|
| Scripts da aplicação | `/usr/local/bin/delphix-ruleset-monitor/` |
| Comando global | `/usr/local/bin/ruleset_monitor.py` |
| Configuração local | `/etc/delphix-ruleset-monitor/config.json` |
| Banco SQLite de execução | `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` |

Para desenvolvimento ou testes, defina `DELPHIX_RULESET_MONITOR_DATA_DIR` para usar outro diretório de dados sem mover os scripts.

## Configuração

Execute o assistente:

```bash
sudo ruleset_monitor.py --configure
```

O assistente solicita a URL, o usuário e a senha do Delphix, as configurações SMTP, o remetente e os destinatários. Ele grava `/etc/delphix-ruleset-monitor/config.json` com permissão `600`.

Os valores com o prefixo `b64:` são apenas ofuscados com Base64; não são criptografados. Proteja `/etc/delphix-ruleset-monitor/config.json` com permissões do sistema de arquivos e, preferencialmente, com um mecanismo externo de gerenciamento de segredos.

## Preparar o par de Rulesets no Delphix

Antes de registrar um par, consulte os Rulesets existentes no Engine para identificar os IDs do Ruleset produtivo e do Ruleset de descoberta:

```bash
sudo ruleset_monitor.py --list-engine-rulesets
```

A consulta exibe o ID, o nome oficial e o tipo de cada Ruleset disponível no Delphix.

Antes de registrar o par nesta ferramenta, prepare o Ruleset de descoberta diretamente no Engine do Delphix Continuous Compliance:

1. Identifique o Ruleset produtivo que será monitorado.
2. Crie um novo Ruleset para ser usado como Ruleset de descoberta.
3. Copie inicialmente para o Ruleset de descoberta o mesmo conteúdo do Ruleset produtivo: tabelas e campos configurados.
4. Verifique se os dois Rulesets representam a mesma estrutura inicial.

Essa etapa é importante porque a primeira sincronização deve começar sem diferenças acidentais. Assim, a linha de base é construída sobre um par alinhado e as diferenças posteriores representam alterações reais na origem.

A ferramenta não cria nem clona Rulesets dentro do Delphix. O Ruleset de descoberta deve existir previamente no Engine, e seu ID será usado ao registrar o par.

## Registrar um par de Rulesets

```bash
sudo ruleset_monitor.py --add-ruleset PROD_ID DISCOVERY_ID
```

Exemplo:

```bash
sudo ruleset_monitor.py --add-ruleset 4 5
```

O programa valida os IDs no Delphix e armazena o par no banco SQLite local.

Depois de registrar o par, crie a linha de base inicial:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID DISCOVERY_ID
```

Por exemplo:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id 4 5
```

A primeira linha de base deve ser criada enquanto o Ruleset de descoberta ainda tiver conteúdo equivalente ao Ruleset produtivo.

Consultar os pares registrados:

```bash
sudo ruleset_monitor.py --list-config
```

## Ativar ou pausar um par

Pausar um par:

```bash
sudo ruleset_monitor.py --set-active PROD_ID DISCOVERY_ID NO
```

Reativá-lo:

```bash
sudo ruleset_monitor.py --set-active PROD_ID DISCOVERY_ID YES
```

Pares pausados não participam de `--audit`.

## Criar ou reconstruir a linha de base

Para todos os Rulesets ativos:

```bash
sudo ruleset_monitor.py --init-baseline
```

Para um par específico:

```bash
sudo ruleset_monitor.py --init-baseline --ruleset-id PROD_ID DISCOVERY_ID
```

Este comando remove as exclusões anteriores do par selecionado e recalcula as diferenças aceitas entre o Ruleset de descoberta e o produtivo. Execute-o somente depois que as diferenças tiverem sido analisadas e aceitas.

Se uma tabela existir na origem, mas intencionalmente não for adicionada a nenhum dos Rulesets, a reconstrução da linha de base registrará uma exclusão para a tabela inteira. Alterações futuras em uma tabela excluída não gerarão alertas até que a exclusão seja substituída por uma nova linha de base depois que a tabela for incorporada ao monitoramento.

## Executar a auditoria

```bash
sudo ruleset_monitor.py --audit
```

O resultado é exibido em três grupos principais:

- Estruturas novas na origem.
- Estruturas removidas da origem.
- Alterações de tipo de dado.

As tabelas adicionadas ou removidas são representadas por meio de seus campos associados.

## Consultas disponíveis

```bash
sudo ruleset_monitor.py --list-prod
sudo ruleset_monitor.py --list-prod --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions
sudo ruleset_monitor.py --list-exclusions --ruleset-id PROD_ID DISCOVERY_ID
sudo ruleset_monitor.py --list-exclusions --filter-table CLIENTES
sudo ruleset_monitor.py --list-engine-rulesets
sudo ruleset_monitor.py --list-orphan-exclusions
```

## Operações complementares

Além do fluxo inicial, a ferramenta permite:

- Consultar os pares configurados com `--list-config`.
- Pausar um par com `--set-active PROD_ID DISCOVERY_ID NO`.
- Reativar um par com `--set-active PROD_ID DISCOVERY_ID YES`.
- Remover um par com `--remove-ruleset`.
- Consultar o inventário produtivo com `--list-prod`.
- Consultar as exclusões com `--list-exclusions`.
- Consultar exclusões órfãs com `--list-orphan-exclusions`.
- Filtrar exclusões por Ruleset ou tabela.
- Limpar todo o estado local com `--purge`.
- Usar `mock_mode` para testes sem conexão com o Delphix.

## Remover um par

```bash
sudo ruleset_monitor.py --remove-ruleset PROD_ID DISCOVERY_ID
```

A remoção exclui a configuração local, o inventário produtivo e as exclusões associadas.

## Limpar o estado local

```bash
sudo ruleset_monitor.py --purge
sudo ruleset_monitor.py --purge -y
```

O banco SQLite é criado em `/var/lib/delphix-ruleset-monitor/delphix_compliance_monitor.db` em uma instalação padrão. Se ele não existir, o programa cria automaticamente a estrutura necessária ao iniciar. Para desenvolvimento ou testes, utilize `DELPHIX_RULESET_MONITOR_DATA_DIR`.

## Execução automática com systemd

```bash
systemctl status delphix-ruleset-monitor.timer
systemctl list-timers delphix-ruleset-monitor.timer
journalctl -u delphix-ruleset-monitor.service
```

O serviço executa `ruleset_monitor.py --audit` como uma tarefa `oneshot`.

Também pode ser executado pelo cron como `root`, usando caminhos absolutos:

```cron
0 8 * * 1-5 /usr/local/bin/ruleset_monitor.py --audit >> /var/log/delphix-ruleset-monitor-cron.log 2>&1
```

Ele não depende do diretório de trabalho nem do diretório pessoal do usuário.

## Modo de teste

Para executar a aplicação sem conexão com o Delphix:

```json
"mock_mode": true
```

O modo mock gera Rulesets, tabelas e campos de exemplo. Ele serve para revisar a saída da CLI e o fluxo geral, mas não valida a configuração real do Engine.

## Recomendação diante de um alerta

1. Revise a tabela e o campo informados no banco de dados de origem.
2. Confirme se a alteração é esperada.
3. Se for necessária proteção, atualize o Ruleset produtivo e atribua o algoritmo adequado.
4. Se a alteração for intencional e não exigir mascaramento, reconstrua a linha de base.
5. Execute a auditoria novamente.

## Considerações de segurança

- Credenciais em Base64 não são criptografadas.
- O cliente desativa a validação de certificados TLS do Delphix.
- O serviço systemd fornecido é executado como `root`.
- Proteja `/etc/delphix-ruleset-monitor/config.json` e revise os destinatários antes de habilitar o envio de e-mails.
