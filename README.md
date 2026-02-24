# AccessBuilder Client Library

Gerenciador reutilizável de clientes AWS com suporte completo a **SSO**, **AWS Organizations**, **Cross-Account Access** e **External ID**.

## Características (v1.1.1)

- ✅ **SSO (IAM Identity Center)**: Autenticação nativa com perfis SSO
- ✅ **AWS Organizations**: Descoberta automática de contas e filtro por OU
- ✅ **External ID**: Segurança cross-account contra "Confused Deputy"
- ✅ **Factory Pattern**: Crie clientes AWS facilmente
- ✅ **Lazy Loading**: @property para clientes principais (s3, ec2, rds)
- ✅ **Cache Automático**: Performance otimizada
- ✅ **5 Estratégias de Autenticação**: SSO, IAM User, Temporary, Cross-Account, Default
- ✅ **Extensível**: Adicione novos serviços sem modificar código core
- ✅ **Type Hints**: Suporte completo a tipagem Python
- ✅ **ConfigLoader**: Auto-detecção com prioridade SSO

## Uso Rápido

### Estratégia 1: SSO (Recomendado)

```python
from AccessBuilder import AWSClientManager

# Configure SSO no ~/.aws/config primeiro
# Execute: aws sso login --profile my-profile

manager = AWSClientManager(
    region='us-east-1',
    sso_profile='my-profile'  # ✨ Novo v1.1.0
)
manager.initialize()

# Usar S3
s3 = manager.s3_client
buckets = s3.list_buckets()

# Usar qualquer outro serviço
ec2 = manager.get_client('ec2')
rds = manager.get_client('rds')
```

### Estratégia 2: IAM User (Credenciais Persistentes)

```python
from AccessBuilder import AWSClientManager

manager = AWSClientManager(
    region='us-east-1',
    aws_access_key_id='AKIA1234567890ABCDEF',
    aws_secret_access_key='wJalrXUtnFEMI/K7MDENG...'
)
manager.initialize()

# Usar S3
s3 = manager.s3_client
buckets = s3.list_buckets()
```

### Estratégia 3: Credenciais Temporárias (STS Token)

```python
manager = AWSClientManager(
    region='us-east-1',
    aws_access_key_id='ASIA1234567890ABCDEF',
    aws_secret_access_key='wJalrXUtnFEMI/K7MDENG...',
    aws_session_token='FwoGZXIvYXdzEOz...'  # Inclua o token!
)
manager.initialize()
```

### Estratégia 4: Cross-Account Role com External ID

```python
manager = AWSClientManager(
    region='us-east-1',
    cross_account_role='arn:aws:iam::123456789012:role/AthenaRole',
    external_id='my-secure-external-id'  # ✨ Novo v1.1.0 (recomendado!)
)
manager.initialize()
```

### Estratégia 5: Credenciais Padrão (EC2 IAM Role)

```python
# Em uma EC2/ECS/Lambda com IAM role
manager = AWSClientManager(region='us-east-1')
manager.initialize()
```

## Novas Funcionalidades v1.1.0

### Descoberta de Contas via AWS Organizations

```python
from AccessBuilder import AWSClientManager, OrganizationsHelper

# Autenticar na Management Account
manager = AWSClientManager(
    region='us-east-1',
    sso_profile='management-account'
)
manager.initialize()

# Descobrir contas
org = OrganizationsHelper(session=manager.session)

# Listar todas as contas
all_accounts = org.list_all_accounts()

# Filtrar por OU
prod_accounts = org.filter_by_ou(['Production'])

for account in prod_accounts:
    print(f"{account['Name']}: {account['Id']}")
```

### Workflow Multi-Conta Completo

```python
# 1. Autenticar via SSO
manager_security = AWSClientManager(
    region='us-east-1',
    sso_profile='security-account'
)
manager_security.initialize()

# 2. Descobrir contas por OU
org = OrganizationsHelper(session=manager_security.session)
accounts = org.filter_by_ou(['Production'])

# 3. Para cada conta, assumir role com External ID
for account in accounts:
    manager_target = AWSClientManager(
        region='us-east-1',
        cross_account_role=f"arn:aws:iam::{account['Id']}:role/Auditor",
        external_id='audit-external-id-2024'
    )
    manager_target.initialize()
    
    s3 = manager_target.s3_client
    ec2 = manager_target.get_client('ec2')
    # ... sua lógica de auditoria aqui
```

### Cache de Credenciais STS em Memória ✨ Novo

O `CredentialCacheManager` permite assumir roles em múltiplas contas e armazenar
as credenciais STS em memória durante a execução, evitando chamadas repetidas ao STS.

**Sobre Permission Sets:**
- As permissões efetivas são as da **role assumida**, não do usuário original
- Se usar AWS SSO, cada permission set cria uma role na conta de destino
- Exemplos de roles: `OrganizationAccountAccessRole`, `AWSReservedSSO_AdministratorAccess_xxx`

```python
from AccessBuilder import CredentialCacheManager
import boto3

# 1. Criar sessão da security/management account
base_session = boto3.Session(profile_name='security-account')

# 2. Criar cache manager
cache = CredentialCacheManager(
    base_session=base_session,
    role_name='OrganizationAccountAccessRole',  # Role a assumir em cada conta
    region='us-east-1',
    external_id='my-secure-id'  # Opcional, para segurança adicional
)

# 3. Assumir roles (escolha uma opção):

# Opção A: Contas específicas
cache.assume_roles_for_accounts(['123456789012', '234567890123'])

# Opção B: Filtrar por OUs
cache.assume_roles_for_ous(['Production', 'Development'])

# Opção C: TODAS as contas da organização
cache.assume_roles_for_all_accounts()

# 4. Usar credenciais para acessar as contas
for account_id in cache.list_cached_accounts():
    manager = cache.get_manager(account_id['account_id'])
    
    if manager:
        s3 = manager.s3_client
        buckets = s3.list_buckets()
        print(f"Conta {account_id['name']}: {len(buckets['Buckets'])} buckets")

# 5. Estatísticas do cache
stats = cache.get_statistics()
print(f"Credenciais válidas: {stats['valid']} de {stats['total']}")

# 6. Renovar todas as credenciais (se expirarem)
cache.refresh_all()
```

Veja exemplo completo em: `examples/exemplo_credential_cache.py`

## Auto-inicialização e tratamento de erros

A partir da versão atual, o `AWSClientManager` tentará inicializar a `boto3.Session`
automaticamente quando você acessar um cliente via `s3_client`, `athena_client` ou
`get_client(...)` caso `initialize()` ainda não tenha sido chamado.

- Conveniência: você pode criar o manager sem chamar `initialize()` explicitamente;
    o acesso ao cliente fará a inicialização automática.
- Segurança/erros: se a inicialização falhar (credenciais inválidas, STS sem
    permissão etc.), será lançada uma `RuntimeError` com a mensagem
    "Falha ao inicializar sessão AWS. Verifique credenciais e permissões." e a
    exceção original ficará encadeada para fins de debug.

Exemplo (auto-init):

```python
from AccessBuilder import AWSClientManager

# Não é necessário chamar initialize() explicitamente
manager = AWSClientManager(region='us-east-1')

# Ao acessar, o manager inicializa automaticamente a sessão
s3 = manager.s3_client
print(type(s3))
```

Se preferir o comportamento antigo (chamar `initialize()` explicitamente),
continue a chamar `manager.initialize()` — o comportamento permanece suportado.


### Usar ConfigLoader para Automação

```python
from AccessBuilder import ConfigLoader

# Carregar do arquivo .env
config = ConfigLoader('.env')
manager = config.get_manager()  # Detecta estratégia automaticamente

# Ou especificar estratégia
manager = config.get_manager('temporary')
```

## 📝 Arquivo .env

Crie um arquivo `.env` com suas credenciais:

```env
# Prioridade 1: SSO (Recomendado) ✨ Novo v1.1.0
AWS_PROFILE=my-sso-profile
AWS_REGION=us-east-1

# External ID (opcional, para AssumeRole) ✨ Novo v1.1.0
AWS_EXTERNAL_ID=my-secure-external-id

# Ou use IAM User:
# AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF
# AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG+bPxRfiCY...

# Ou use Temp Token (adicione se usar STS):
# AWS_SESSION_TOKEN=FwoGZXIvYXdzEOz...

# Ou use Cross-Account:
# AWS_CROSS_ACCOUNT_ROLE=arn:aws:iam::123456789012:role/AthenaRole
# AWS_EXTERNAL_ID=my-external-id
```

**Segurança**: Nunca commite `.env` no Git. Use `.gitignore`:
```
.env
*.key
secrets/
```

**Dica**: Veja [.env.example](.env.example) para referência completa.

## Recursos Principais

### @property (Interface Limpa)

```python
manager.initialize()

# Acesso simples como atributo
s3 = manager.s3_client      # Lazy loading automático
athena = manager.athena_client

# Transparente: sintaxe de atributo, lógica de método
```

### Factory Method (Extensibilidade)

```python
# Qualquer serviço AWS
dynamodb = manager.get_client('dynamodb')
lambda_svc = manager.get_client('lambda')
sqs = manager.get_client('sqs')
ec2 = manager.get_client('ec2')

# Com argumentos customizados
s3_custom = manager.get_client('s3', endpoint_url='http://localhost:9000')
```

### Cache Management

```python
# Listar clientes ativos
active = manager.list_active_clients()
print(active)  # ['s3', 'athena', 'dynamodb']

# Limpar cache específico
manager.clear_client_cache('s3')

# Limpar tudo
manager.clear_client_cache()
```

### Rotação de Credenciais

```python
# Token expirado? Rotacionar!
manager.rotate_credentials(
    aws_access_key_id='ASIA_NEW_...',
    aws_secret_access_key='new_secret...',
    aws_session_token='FwoG_NEW_...'
)
# Próximas requisições usam novas credenciais
```

## Logging

Habilite logs para debug:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('aws_client_lib')
logger.setLevel(logging.DEBUG)
```

Saída esperada:
```
INFO:aws_client_lib.config:ConfigLoader inicializado (env_path=.env)
INFO:aws_client_lib.aws_client:Using IAM User (access_key_id provided)
DEBUG:aws_client_lib.aws_client:Creating S3 client (lazy loading)
INFO:aws_client_lib.aws_client:Session AWS inicializada para região: us-east-1
```

## Exemplos Completos

### Listar buckets S3

```python
from AccessBuilder import AWSClientManager

manager = AWSClientManager(
    region='us-east-1',
    aws_access_key_id='AKIA...',
    aws_secret_access_key='wJalr...'
)
manager.initialize()

s3 = manager.s3_client
response = s3.list_buckets()
for bucket in response['Buckets']:
    print(bucket['Name'])
```

### Executar query Athena

```python
from AccessBuilder import ConfigLoader

config = ConfigLoader('.env')
manager = config.get_manager()

athena = manager.athena_client
response = athena.start_query_execution(
    QueryString='SELECT COUNT(*) FROM table',
    QueryExecutionContext={'Database': 'default'},
    ResultConfiguration={'OutputLocation': 's3://bucket/prefix/'}
)
print(response['QueryExecutionId'])
```

### Multi-serviço

```python
from AccessBuilder import ConfigLoader

config = ConfigLoader('.env')
manager = config.get_manager()

# S3
s3 = manager.s3_client
s3.put_object(Bucket='bucket', Key='file', Body=b'data')

# DynamoDB
dynamodb = manager.get_client('dynamodb')
dynamodb.put_item(TableName='table', Item={'id': {'S': 'value'}})

# SQS
sqs = manager.get_client('sqs')
sqs.send_message(QueueUrl='https://...', MessageBody='hello')

# Lambda
lambda_svc = manager.get_client('lambda')
lambda_svc.invoke(FunctionName='my-function', Payload='{}')
```

## Arquitetura

### Camadas

```
┌─────────────────────────────────────┐
│   Seu Código da Aplicação           │
│   (main.py, app.py, etc)            │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│   ConfigLoader                      │
│   - Carrega .env / Env Vars         │
│   - Cria AWSClientManager           │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│   AWSClientManager                  │
│   - @property s3_client             │
│   - @property athena_client         │
│   - get_client(service)             │
│   - Cache Management                │
│   - Credential Rotation             │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│   boto3.Session                     │
│   (Centraliza credenciais)          │
└──────────────┬──────────────────────┘
               │
┌──────────────┴──────────────────────┐
│   AWS Services                      │
│   (S3, Athena, DynamoDB, etc)       │
└─────────────────────────────────────┘
```

### Design Patterns

1. **Factory Pattern**: `get_client(service_name)` cria clientes dinamicamente
2. **Property Pattern**: `@property s3_client` fornece interface limpa
3. **Lazy Loading**: Clientes criados apenas quando acessados
4. **Cache Pattern**: Clientes reutilizados em próximos acessos
5. **Credential Rotation**: Suporte a renovação de tokens

## Desenvolvimento

### Criar ambiente virtual

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### Instalar com dependências de dev

```bash
pip install -e ".[dev]"
```

### Rodar testes

```bash
pytest tests/ -v --cov=AccessBuilder
```

### Code style

```bash
black AccessBuilder
flake8 AccessBuilder
mypy AccessBuilder
```

## License

MIT License - veja LICENSE arquivo

## Documentação Adicional

- **[Novas Funcionalidades v1.1.1](docs/NEW_FEATURES_v1.1.1.md)** - Correção da função de validação de expiração de credenciais temporárias  
- **[Novas Funcionalidades v1.1.0](docs/NEW_FEATURES_v1.1.0.md)** - Guia completo de SSO, Organizations e External ID
- **[Exemplos Práticos](examples/exemplo_completo_sso_org.py)** - 6 exemplos funcionais completos
- **[Configuração .env](.env.example)** - Template de configuração com todos os cenários

## O Que Há de Novo

### v1.1.1 (Fevereiro 2026)

- ✅ Correção da função de validação de expiração de credenciais temporárias 

### v1.1.0 (Fevereiro 2026)

- ✨ **SSO Authentication**: Suporte completo a IAM Identity Center
- ✨ **AWS Organizations**: Descoberta automática de contas e filtro por OU
- ✨ **External ID**: Segurança cross-account contra "Confused Deputy Problem"
- ✨ **ConfigLoader melhorado**: Auto-detecção de SSO profiles
- 📝 **Documentação expandida**: Guias, exemplos e troubleshooting
- 🔒 **Segurança aprimorada**: Validação de credenciais e expiration checking

### v1.0.0

- ✅ Factory Pattern e Lazy Loading
- ✅ 4 estratégias de autenticação básicas
- ✅ Cache automático de clientes
- ✅ ConfigLoader com .env

## Contribuições

Contribuições são bem-vindas! Abra um PR ou issue.

---

**Versão:** 1.1.1
**Data:** 11 de fevereiro de 2026  
Feito com ❤️ para a comunidade AWS
