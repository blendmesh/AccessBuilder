"""
aws_client.py - Gerenciador de Clientes AWS Reutilizável

Classe principal para gerenciar criação e autenticação de clientes AWS.
Implementa Factory Pattern + @property para máxima escalabilidade.

Compatível com:
  - Python 3.7+
  - boto3 1.17+
  - Qualquer aplicação AWS

Uso:
    from AccessBuilder import AWSClientManager
    
    manager = AWSClientManager(region='us-east-1', aws_access_key_id='AKIA...')
    manager.initialize()
    s3 = manager.s3_client
"""

import logging
import boto3
from botocore.exceptions import ClientError
from botocore.client import BaseClient
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class AWSClientManager:
    """
    Gerencia criação e autenticação de clientes AWS.
    
    Implementa Factory Pattern + @property para máxima escalabilidade e usabilidade:
    - Session centralizada para gerenciar credenciais
    - @property para serviços principais (s3, athena) com lazy loading
    - get_client() factory method para extensibilidade
    - Cache automático para performance
    
    Estratégias de autenticação suportadas:
      1. IAM User (credenciais persistentes)
      2. Credenciais Temporárias (com session_token)
      3. Cross-Account Role (assume_role via STS)
      4. Padrão (IAM role da EC2/ECS)
    """
    
    def __init__(
        self,
        region: str,
        cross_account_role: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        sso_profile: Optional[str] = None,
        external_id: Optional[str] = None,
    ):
        """
        Inicializa gerenciador de clientes AWS.
        
        Args:
            region: Região AWS (ex: 'us-east-1', 'eu-west-1')
            cross_account_role: ARN da role para cross-account (opcional)
                Ex: 'arn:aws:iam::123456789012:role/AthenaRole'
            aws_access_key_id: Access key ID (opcional)
                Para IAM user: começa com 'AKIA'
                Para temp: começa com 'ASIA'
            aws_secret_access_key: Secret access key (opcional)
            aws_session_token: Session token (opcional, apenas para temp credentials)
            sso_profile: Nome do perfil SSO configurado no ~/.aws/config (opcional)
                Ex: 'my-sso-profile'
            external_id: External ID para AssumeRole cross-account (opcional)
                Ex: 'my-secure-external-id'
                Usado para prevenir "Confused Deputy" problem
            
        Nota:
            Prioridade de autenticação:
            1. Credenciais fornecidas (access_key + secret_key ± session_token)
            2. Cross-account role (assume_role)
            3. Credenciais padrão (IAM role da EC2)
            
        Exemplo:
            # IAM User
            manager = AWSClientManager(
                region='us-east-1',
                aws_access_key_id='AKIA1234567890ABCDEF',
                aws_secret_access_key='wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY'
            )
            
            # Credenciais Temporárias
            manager = AWSClientManager(
                region='us-east-1',
                aws_access_key_id='ASIA1234567890ABCDEF',
                aws_secret_access_key='wJalrXUtnFEMI/K7MDENG...',
                aws_session_token='FwoGZXIvYXdzEO3...'
            )
            
            # Cross-Account
            manager = AWSClientManager(
                region='us-east-1',
                cross_account_role='arn:aws:iam::123456789012:role/AthenaRole'
            )
            
            # EC2 IAM Role (nenhum parâmetro de credencial)
            manager = AWSClientManager(region='us-east-1')
        """
        self.region = region
        self.cross_account_role = cross_account_role
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_session_token = aws_session_token
        self.sso_profile = sso_profile
        self.external_id = external_id
        
        # Session centralizada (Factory Pattern)
        self.session: Optional[boto3.Session] = None
        
        # Cache de clientes (lazy loading com @property)
        self._s3_client = None
        self._athena_client = None
        
        # Cache para factory method (extensibilidade)
        self._clients_cache: Dict[str, any] = {}
        
    def initialize(self) -> None:
        """
        Inicializa a sessão AWS com as credenciais apropriadas.
        
        Deve ser chamado uma vez antes de usar qualquer cliente.
        
        Raises:
            ClientError: Se houver erro ao conectar com AWS
            
        Exemplo:
            manager = AWSClientManager(region='us-east-1', ...)
            manager.initialize()  # Cria a sessão
            s3 = manager.s3_client  # Agora pode usar clientes
        """
        try:
            # Prioridade 1: Perfil SSO
            if self.sso_profile:
                self._initialize_with_sso()
            # Prioridade 2: Credenciais fornecidas diretamente
            elif self.aws_access_key_id and self.aws_secret_access_key:
                self._initialize_with_provided_credentials()
            # Prioridade 3: Cross-account role
            elif self.cross_account_role:
                self._initialize_with_assumed_role()
            # Prioridade 4: Credenciais padrão (IAM role da EC2)
            else:
                self._initialize_with_default_credentials()

            logger.info(f"Session AWS inicializada para região: {self.region}")

        except Exception as e:
            # Log mais detalhado e levantar erro claro para o usuário final.
            logger.error(f"Falha ao inicializar session AWS: {e}")
            raise RuntimeError(
                "Falha ao inicializar sessão AWS. Verifique credenciais e permissões."
            ) from e

    def _ensure_session(self) -> None:
        """
        Verifica se a session AWS foi inicializada.
        Se a sessão não estiver inicializada, inicializa automaticamente
        chamando `initialize()`. Erros de autenticação são propagados.
        """
        if self.session is None:
            logger.debug("Session AWS não inicializada — inicializando automaticamente")
            # initialize() pode lançar ClientError se as credenciais forem inválidas;
            # deixamos a exceção propagar para o chamador tratar.
            self.initialize()
            
    def _initialize_with_sso(self) -> None:
        """
        Inicializa session com perfil SSO.
        
        Usa o perfil SSO configurado no ~/.aws/config.
        """
        try:
            from .sso_auth import SSOAuthStrategy
            
            logger.info(f"Inicializando com perfil SSO: {self.sso_profile}")
            sso = SSOAuthStrategy(profile_name=self.sso_profile)
            self.session = sso.get_session()
            
            # Log da identidade para debug
            identity = sso.get_caller_identity()
            logger.info(f"SSO autenticado: {identity['Arn']}")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar com SSO: {e}")
            raise
    
    def _initialize_with_default_credentials(self) -> None:
        """Inicializa session com credenciais padrão (IAM role da EC2)."""
        self.session = boto3.Session(region_name=self.region)
        logger.info("Usando credenciais padrão (IAM role da EC2)")
        
    def _initialize_with_provided_credentials(self) -> None:
        """
        Inicializa session com credenciais fornecidas diretamente.
        
        Suporta:
        - IAM User: access_key_id + secret_access_key
        - Credenciais Temporárias: access_key_id + secret_access_key + session_token
        """
        try:
            auth_type = "IAM User"
            kwargs = {
                'region_name': self.region,
                'aws_access_key_id': self.aws_access_key_id,
                'aws_secret_access_key': self.aws_secret_access_key,
            }
            
            # Se houver session token, é credencial temporária
            if self.aws_session_token:
                kwargs['aws_session_token'] = self.aws_session_token
                auth_type = "Credenciais Temporárias"
            
            self.session = boto3.Session(**kwargs)
            logger.info(f"Usando {auth_type} (access_key_id fornecido)")
            
        except ClientError as e:
            logger.error(f"Erro ao inicializar com credenciais fornecidas: {e}")
            raise
        
    def _initialize_with_assumed_role(self) -> None:
        """
        Assume role em outra conta para acessar serviços AWS.
        
        Útil para multi-account AWS onde você precisa acessar recursos
        em outras contas sem ter credenciais diretas delas.
        
        Suporta External ID para prevenir "Confused Deputy" problem.
        """
        sts_client = boto3.client('sts', region_name=self.region)
        
        try:
            logger.info(f"Assumindo role: {self.cross_account_role}")
            
            assume_role_params = {
                'RoleArn': self.cross_account_role,
                'RoleSessionName': 'aws-client-manager-session',
                'DurationSeconds': 3600
            }
            
            # Adicionar External ID se fornecido
            if self.external_id:
                assume_role_params['ExternalId'] = self.external_id
                logger.info(f"Usando External ID para segurança adicional")
            
            response = sts_client.assume_role(**assume_role_params)
            
            credentials = response['Credentials']
            
            self.session = boto3.Session(
                region_name=self.region,
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken']
            )
            
            logger.info("Role assumida com sucesso")
            
        except ClientError as e:
            logger.error(f"Erro ao assumir role: {e}")
            raise
    
    # ============================================================================
    # @property: Interface limpa para serviços principais (Microserviço Pattern)
    # ============================================================================
    
    @property
    def s3_client(self) -> BaseClient:
        """
        Acesso lazy-loaded ao cliente S3.
        
        Implementação:
        - Lazy loading: cria apenas na primeira utilização
        - Caching: reutiliza em próximas acessos
        - Transparente: sintaxe de atributo, mas lógica de método
        
        Returns:
            boto3.BaseClient: Cliente S3 configurado
            
        Exemplo:
            manager.initialize()
            s3 = manager.s3_client
            s3.put_object(Bucket='bucket', Key='file', Body=b'data')
            s3.get_object(Bucket='bucket', Key='file')
        """
        if self._s3_client is None:
            self._ensure_session()
            logger.debug("Criando cliente S3 (lazy loading)")
            self._s3_client = self.session.client('s3')
        return self._s3_client
    
    @property
    def athena_client(self) -> BaseClient:
        """
        Acesso lazy-loaded ao cliente Athena.
        
        Implementação:
        - Lazy loading: cria apenas na primeira utilização
        - Caching: reutiliza em próximas acessos
        - Transparente: sintaxe de atributo, mas lógica de método
        
        Returns:
            boto3.BaseClient: Cliente Athena configurado
            
        Exemplo:
            manager.initialize()
            athena = manager.athena_client
            athena.start_query_execution(
                QueryString='SELECT * FROM table',
                QueryExecutionContext={'Database': 'default'}
            )
        """
        if self._athena_client is None:
            self._ensure_session()
            logger.debug("Criando cliente Athena (lazy loading)")
            self._athena_client = self.session.client('athena')
        return self._athena_client
    
    # ============================================================================
    # Factory Method: Padrão para extensibilidade (Enterprise Pattern)
    # ============================================================================
    
    def get_client(self, service_name: str, **kwargs) -> BaseClient:
        """
        Factory method para obter cliente AWS de qualquer serviço.
        
        Implementação:
        - Centraliza criação de clientes
        - Suporta qualquer serviço AWS (não apenas S3/Athena)
        - Cache automático por service + kwargs
        - Extensível sem modificar código existente
        
        Args:
            service_name: Nome do serviço AWS (ex: s3, athena, dynamodb, lambda, sqs, ec2, etc)
            **kwargs: Argumentos adicionais para o client (ex: endpoint_url, region_name, etc)
        
        Returns:
            boto3.BaseClient: Cliente do serviço AWS
            
        Raises:
            Exception: Se houver erro ao criar o cliente
        
        Exemplos:
            # Serviços principais com @property (recomendado)
            s3 = manager.s3_client
            athena = manager.athena_client
            
            # Serviços adicionais com factory method
            dynamodb = manager.get_client('dynamodb')
            lambda_svc = manager.get_client('lambda')
            sqs = manager.get_client('sqs')
            ec2 = manager.get_client('ec2')
            
            # Com argumentos customizados
            s3_custom = manager.get_client('s3', endpoint_url='http://localhost:9000')
            dynamodb_custom = manager.get_client('dynamodb', endpoint_url='http://localhost:8000')
        """
        # Gerar chave de cache baseada no serviço e argumentos
        cache_key = self._generate_cache_key(service_name, kwargs)
        
        # Verificar se cliente já existe em cache
        if cache_key in self._clients_cache:
            logger.debug(f"Retornando cliente {service_name} do cache")
            return self._clients_cache[cache_key]
        
        # Criar novo cliente
        self._ensure_session()
        logger.info(f"Criando novo cliente: {service_name}")
        try:
            client = self.session.client(service_name, **kwargs)
            self._clients_cache[cache_key] = client
            return client
        
        except Exception as e:
            logger.error(f"Erro ao criar cliente {service_name}: {e}")
            raise
    
    def _generate_cache_key(self, service_name: str, kwargs: Dict) -> str:
        """
        Gera chave única para cache baseado no serviço e argumentos.
        
        Args:
            service_name: Nome do serviço
            kwargs: Argumentos adicionais
        
        Returns:
            str: Chave de cache (ex: 's3' ou 's3:endpoint_url=http://...')
        """
        if not kwargs:
            return service_name
        
        # Criar string de argumentos para chave de cache
        kwargs_str = ':'.join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{service_name}:{kwargs_str}"
    
    # ============================================================================
    # Gerenciamento de Cache e Sessão
    # ============================================================================
    
    def list_active_clients(self) -> list:
        """
        Lista todos os clientes ativos em cache.
        
        Útil para:
        - Auditoria: saber quais serviços estão em uso
        - Debugging: verificar estado do manager
        - Monitoramento: rastrear recursos ativos
        
        Returns:
            list: Lista de strings com nomes dos clientes ativos
        
        Exemplo:
            manager.initialize()
            _ = manager.s3_client
            _ = manager.get_client('dynamodb')
            
            active = manager.list_active_clients()
            print(active)  # ['s3', 'athena', 'dynamodb']
        """
        active = []
        
        if self._s3_client is not None:
            active.append('s3')
        if self._athena_client is not None:
            active.append('athena')
        
        # Adicionar clientes do cache geral
        active.extend(self._clients_cache.keys())
        
        return active
    
    def clear_client_cache(self, service_name: Optional[str] = None) -> None:
        """
        Limpa cache de clientes.
        
        Útil para:
        - Rotação de credenciais: invalidar clientes antigos
        - Limpeza de memória: remover clientes não utilizados
        - Teste: resetar estado
        
        Args:
            service_name: Se fornecido, limpa apenas esse serviço. Senão limpa tudo.
        
        Exemplo:
            # Limpar apenas S3
            manager.clear_client_cache('s3')
            
            # Limpar tudo
            manager.clear_client_cache()
        """
        if service_name:
            # Limpar apenas um serviço
            if service_name == 's3':
                self._s3_client = None
                logger.info("Cache de S3 limpo")
            elif service_name == 'athena':
                self._athena_client = None
                logger.info("Cache de Athena limpo")
            else:
                # Remover do cache geral
                keys_to_remove = [k for k in self._clients_cache.keys() 
                                if k.startswith(service_name)]
                for key in keys_to_remove:
                    del self._clients_cache[key]
                logger.info(f"Cache de {service_name} limpo ({len(keys_to_remove)} cliente(s))")
        else:
            # Limpar tudo
            self._s3_client = None
            self._athena_client = None
            self._clients_cache.clear()
            logger.info("Cache completamente limpo")
    
    def rotate_credentials(
        self,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
    ) -> None:
        """
        Rotaciona credenciais e invalida clients antigos.
        
        Cenários:
        - Token temporário expirou → renovar com novo token
        - Credenciais comprometidas → usar novas credenciais
        - Troca de conta AWS → atualizar access_key
        
        Args:
            aws_access_key_id: Nova access key
            aws_secret_access_key: Novo secret key
            aws_session_token: Novo session token (opcional)
        
        Exemplo:
            # Renovar credenciais temporárias
            manager.rotate_credentials(
                aws_access_key_id='ASIA_NEW_...',
                aws_secret_access_key='new_secret...',
                aws_session_token='FwoG_NEW_...'
            )
            
            # Próximas requisições usarão novas credenciais
        """
        logger.info("Rotacionando credenciais AWS")
        
        # Atualizar credenciais
        if aws_access_key_id:
            self.aws_access_key_id = aws_access_key_id
        if aws_secret_access_key:
            self.aws_secret_access_key = aws_secret_access_key
        if aws_session_token is not None:
            self.aws_session_token = aws_session_token
        
        # Reinicializar session com novas credenciais
        self.session = None
        self.initialize()
        
        # Limpar cache (clients antigos usariam credenciais antigas)
        self.clear_client_cache()
        
        logger.info("Credenciais rotacionadas e cache limpo")
