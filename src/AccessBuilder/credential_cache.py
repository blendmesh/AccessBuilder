"""
credential_cache.py - Cache de Credenciais STS em Memória

Gerencia credenciais temporárias STS para múltiplas contas AWS,
armazenando-as em memória durante a execução.

Uso:
    from AccessBuilder.credential_cache import CredentialCacheManager
    
    # A partir de uma security account
    cache = CredentialCacheManager(
        base_session=boto3.Session(profile_name='security-account'),
        role_name='OrganizationAccountAccessRole',  # ou permission set role
        region='us-east-1'
    )
    
    # Assumir roles em contas específicas
    cache.assume_roles_for_accounts(['123456789012', '234567890123'])
    
    # Ou assumir em todas as contas de OUs específicas
    cache.assume_roles_for_ous(['Production', 'Development'])
    
    # Ou assumir em todas as contas da organização
    cache.assume_roles_for_all_accounts()
    
    # Obter client manager para uma conta
    manager = cache.get_manager('123456789012')
    s3 = manager.s3_client
"""

import boto3
from botocore.exceptions import ClientError
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from .organizations import OrganizationsHelper

logger = logging.getLogger(__name__)


@dataclass
class CachedCredential:
    """Armazena credenciais temporárias STS em memória."""
    
    account_id: str
    account_name: str
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: datetime
    role_arn: str
    
    def is_expired(self) -> bool:
        """Verifica se a credencial está expirada."""
        # Considera expirada se faltar menos de 5 minutos
        return datetime.now(timezone.utc) >= (self.expiration - timedelta(minutes=5))
    
    def to_dict(self) -> Dict:
        """Converte para dict compatível com AWSClientManager."""
        return {
            'aws_access_key_id': self.access_key_id,
            'aws_secret_access_key': self.secret_access_key,
            'aws_session_token': self.session_token
        }


class CredentialCacheManager:
    """
    Gerencia cache de credenciais STS para múltiplas contas AWS.
    
    Características:
    - Armazena credenciais STS em memória (não persiste)
    - Suporta filtros por contas, OUs ou todas as contas
    - Gerencia expiração e renovação automática
    - Cria AWSClientManager pré-configurados por conta
    
    Fluxo:
    1. Autentica na security/management account
    2. Lista contas (via filtros ou Organizations)
    3. Para cada conta, executa AssumeRole
    4. Armazena credenciais temporárias em memória
    5. Fornece AWSClientManager por demanda
    
    Sobre Permission Sets:
    - O role_name especificado determina as permissões efetivas
    - Se usar AWS SSO, cada permission set cria uma role (ex: AWSAdministratorAccess)
    - As permissões serão as da ROLE assumida, não do usuário original
    """
    
    def __init__(
        self,
        base_session: boto3.Session,
        role_name: str,
        region: str = 'us-east-1',
        external_id: Optional[str] = None,
        session_duration: int = 3600
    ):
        """
        Inicializa o gerenciador de cache de credenciais.
        
        Args:
            base_session: Sessão boto3 da security/management account
            role_name: Nome da role a assumir em cada conta
                      Ex: 'OrganizationAccountAccessRole'
                      Ex: 'AWSReservedSSO_AdministratorAccess_xxxxx' (SSO permission set)
            region: Região AWS padrão
            external_id: External ID para AssumeRole (opcional, para segurança)
            session_duration: Duração da sessão STS em segundos (padrão: 3600 = 1h)
        
        Exemplo:
            # Com perfil SSO
            session = boto3.Session(profile_name='security-account')
            cache = CredentialCacheManager(
                base_session=session,
                role_name='OrganizationAccountAccessRole',
                region='us-east-1'
            )
            
            # Com external ID para segurança
            cache = CredentialCacheManager(
                base_session=session,
                role_name='OrganizationAccountAccessRole',
                external_id='my-secure-id-12345'
            )
        """
        self.base_session = base_session
        self.role_name = role_name
        self.region = region
        self.external_id = external_id
        self.session_duration = session_duration
        
        # Cache de credenciais: {account_id: CachedCredential}
        self._cache: Dict[str, CachedCredential] = {}
        
        # Cliente STS da security account
        self.sts_client = self.base_session.client('sts', region_name=region)
        
        # Helper para Organizations (lazy-loaded)
        self._org_helper: Optional[OrganizationsHelper] = None
        
        # Identidade da security account
        self._base_identity = self.sts_client.get_caller_identity()
        
        logger.info(f"✅ CredentialCacheManager inicializado")
        logger.info(f"   Security Account: {self._base_identity['Account']}")
        logger.info(f"   Role Name: {self.role_name}")
        logger.info(f"   Region: {self.region}")
        if self.external_id:
            logger.info(f"   External ID: {self.external_id[:8]}...")
    
    @property
    def org_helper(self) -> OrganizationsHelper:
        """Lazy-load do OrganizationsHelper."""
        if self._org_helper is None:
            self._org_helper = OrganizationsHelper(self.base_session)
        return self._org_helper
    
    def assume_role_for_account(
        self,
        account_id: str,
        account_name: Optional[str] = None
    ) -> Optional[CachedCredential]:
        """
        Assume role em uma conta específica e armazena credenciais.
        
        Args:
            account_id: ID da conta AWS (12 dígitos)
            account_name: Nome da conta (opcional, para logs)
        
        Returns:
            CachedCredential ou None se falhar
        
        Exemplo:
            cache = CredentialCacheManager(...)
            cred = cache.assume_role_for_account('123456789012', 'Production')
            if cred:
                print(f"Credencial obtida, expira em: {cred.expiration}")
        """
        role_arn = f"arn:aws:iam::{account_id}:role/{self.role_name}"
        account_display = account_name or account_id
        
        try:
            logger.info(f"Assumindo role para conta: {account_display} ({account_id})")
            logger.debug(f"   Role ARN: {role_arn}")
            
            # Parâmetros do AssumeRole
            assume_params = {
                'RoleArn': role_arn,
                'RoleSessionName': f'credential-cache-{account_id}',
                'DurationSeconds': self.session_duration
            }
            
            # Adicionar External ID se fornecido
            if self.external_id:
                assume_params['ExternalId'] = self.external_id
            
            # Executar AssumeRole
            response = self.sts_client.assume_role(**assume_params)
            credentials = response['Credentials']
            
            # Criar objeto de credencial
            cached_cred = CachedCredential(
                account_id=account_id,
                account_name=account_name or account_id,
                access_key_id=credentials['AccessKeyId'],
                secret_access_key=credentials['SecretAccessKey'],
                session_token=credentials['SessionToken'],
                expiration=credentials['Expiration'],
                role_arn=role_arn
            )
            
            # Armazenar em cache
            self._cache[account_id] = cached_cred
            
            logger.info(f"✅ Credencial obtida para {account_display}")
            logger.debug(f"   Expira em: {cached_cred.expiration}")
            
            return cached_cred
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            
            logger.error(
                f"❌ Falha ao assumir role para {account_display}: "
                f"{error_code} - {error_msg}"
            )
            
            if error_code == 'AccessDenied':
                logger.warning(
                    f"   Verifique se a role '{self.role_name}' existe na conta "
                    f"e permite AssumeRole da security account"
                )
            
            return None
        
        except Exception as e:
            logger.error(f"❌ Erro inesperado ao assumir role para {account_display}: {e}")
            return None
    
    def assume_roles_for_accounts(
        self,
        account_ids: List[str],
        account_names: Optional[Dict[str, str]] = None
    ) -> Dict[str, CachedCredential]:
        """
        Assume roles para uma lista de contas específicas.
        
        Args:
            account_ids: Lista de IDs de contas
            account_names: Dict opcional mapeando account_id -> nome
        
        Returns:
            Dict {account_id: CachedCredential} com credenciais obtidas
        
        Exemplo:
            cache = CredentialCacheManager(...)
            
            # Apenas IDs
            creds = cache.assume_roles_for_accounts([
                '123456789012',
                '234567890123'
            ])
            
            # Com nomes
            creds = cache.assume_roles_for_accounts(
                account_ids=['123456789012', '234567890123'],
                account_names={
                    '123456789012': 'Production',
                    '234567890123': 'Development'
                }
            )
            
            print(f"Credenciais obtidas para {len(creds)} contas")
        """
        logger.info(f"Assumindo roles para {len(account_ids)} contas...")
        
        account_names = account_names or {}
        results = {}
        
        for account_id in account_ids:
            account_name = account_names.get(account_id)
            cred = self.assume_role_for_account(account_id, account_name)
            
            if cred:
                results[account_id] = cred
        
        logger.info(
            f"✅ Credenciais obtidas: {len(results)} de {len(account_ids)} contas"
        )
        
        return results
    
    def assume_roles_for_ous(
        self,
        ou_names: List[str]
    ) -> Dict[str, CachedCredential]:
        """
        Assume roles para todas as contas em OUs específicas.
        
        Requer permissões de Organizations na security account.
        
        Args:
            ou_names: Lista de nomes de OUs (ex: ['Production', 'Development'])
        
        Returns:
            Dict {account_id: CachedCredential} com credenciais obtidas
        
        Exemplo:
            cache = CredentialCacheManager(...)
            
            # Assumir em todas as contas de Production e Development
            creds = cache.assume_roles_for_ous(['Production', 'Development'])
            
            print(f"Credenciais obtidas para {len(creds)} contas")
        """
        logger.info(f"Buscando contas nas OUs: {ou_names}")
        
        # Usar OrganizationsHelper para filtrar contas
        accounts = self.org_helper.filter_by_ou(ou_names)
        
        logger.info(f"Encontradas {len(accounts)} contas nas OUs especificadas")
        
        # Criar mapa de account_id -> nome
        account_ids = [acc['Id'] for acc in accounts]
        account_names = {acc['Id']: acc['Name'] for acc in accounts}
        
        # Assumir roles
        return self.assume_roles_for_accounts(account_ids, account_names)
    
    def assume_roles_for_all_accounts(
        self,
        status: str = 'ACTIVE'
    ) -> Dict[str, CachedCredential]:
        """
        Assume roles para TODAS as contas da organização.
        
        Requer permissões de Organizations na security account.
        
        Args:
            status: Filtro de status ('ACTIVE', 'SUSPENDED', ou None para todas)
        
        Returns:
            Dict {account_id: CachedCredential} com credenciais obtidas
        
        Exemplo:
            cache = CredentialCacheManager(...)
            
            # Assumir em TODAS as contas ativas
            creds = cache.assume_roles_for_all_accounts()
            
            print(f"Credenciais obtidas para {len(creds)} contas")
        """
        logger.info("Buscando TODAS as contas da organização...")
        
        # Usar OrganizationsHelper para listar todas as contas
        accounts = self.org_helper.list_all_accounts(status=status)
        
        logger.info(f"Encontradas {len(accounts)} contas (status={status})")
        
        # Criar mapa de account_id -> nome
        account_ids = [acc['Id'] for acc in accounts]
        account_names = {acc['Id']: acc['Name'] for acc in accounts}
        
        # Assumir roles
        return self.assume_roles_for_accounts(account_ids, account_names)
    
    def get_cached_credential(
        self,
        account_id: str,
        auto_refresh: bool = True
    ) -> Optional[CachedCredential]:
        """
        Obtém credencial em cache para uma conta.
        
        Args:
            account_id: ID da conta
            auto_refresh: Se True, renova automaticamente se expirada
        
        Returns:
            CachedCredential ou None se não existir
        
        Exemplo:
            cache = CredentialCacheManager(...)
            cache.assume_roles_for_accounts(['123456789012'])
            
            # Obter credencial
            cred = cache.get_cached_credential('123456789012')
            if cred:
                print(f"Access Key: {cred.access_key_id[:8]}...")
        """
        if account_id not in self._cache:
            logger.warning(f"Credencial não encontrada em cache para conta: {account_id}")
            return None
        
        cred = self._cache[account_id]
        
        # Verificar expiração
        if cred.is_expired():
            logger.info(f"Credencial expirada para conta: {account_id}")
            
            if auto_refresh:
                logger.info("Auto-refresh habilitado, renovando credencial...")
                cred = self.assume_role_for_account(account_id, cred.account_name)
            else:
                logger.warning("Auto-refresh desabilitado, retornando None")
                return None
        
        return cred
    
    def get_manager(
        self,
        account_id: str,
        auto_refresh: bool = True
    ) -> Optional['AWSClientManager']:
        """
        Obtém AWSClientManager pré-configurado para uma conta.
        
        Args:
            account_id: ID da conta
            auto_refresh: Se True, renova credencial se expirada
        
        Returns:
            AWSClientManager configurado ou None se não houver credencial
        
        Exemplo:
            cache = CredentialCacheManager(...)
            cache.assume_roles_for_accounts(['123456789012'])
            
            # Obter manager e usar
            manager = cache.get_manager('123456789012')
            if manager:
                s3 = manager.s3_client
                buckets = s3.list_buckets()
        """
        from .aws_client import AWSClientManager
        
        cred = self.get_cached_credential(account_id, auto_refresh)
        
        if cred is None:
            return None
        
        # Criar AWSClientManager com as credenciais
        manager = AWSClientManager(
            region=self.region,
            aws_access_key_id=cred.access_key_id,
            aws_secret_access_key=cred.secret_access_key,
            aws_session_token=cred.session_token
        )
        
        # Não chamar initialize() - será chamado automaticamente
        
        return manager
    
    def list_cached_accounts(self) -> List[Dict]:
        """
        Lista todas as contas com credenciais em cache.
        
        Returns:
            Lista de dicts com informações das contas
        
        Exemplo:
            cache = CredentialCacheManager(...)
            cache.assume_roles_for_all_accounts()
            
            accounts = cache.list_cached_accounts()
            for acc in accounts:
                print(f"{acc['name']} ({acc['account_id']}): {'Expirado' if acc['expired'] else 'Válido'}")
        """
        accounts = []
        
        for account_id, cred in self._cache.items():
            accounts.append({
                'account_id': account_id,
                'name': cred.account_name,
                'role_arn': cred.role_arn,
                'expiration': cred.expiration,
                'expired': cred.is_expired(),
                'time_remaining': (cred.expiration - datetime.utcnow()).total_seconds()
            })
        
        return accounts
    
    def clear_cache(self, account_id: Optional[str] = None) -> None:
        """
        Limpa credenciais do cache.
        
        Args:
            account_id: Se fornecido, limpa apenas essa conta. Senão limpa tudo.
        
        Exemplo:
            cache = CredentialCacheManager(...)
            
            # Limpar apenas uma conta
            cache.clear_cache('123456789012')
            
            # Limpar tudo
            cache.clear_cache()
        """
        if account_id:
            if account_id in self._cache:
                del self._cache[account_id]
                logger.info(f"Credencial removida do cache: {account_id}")
            else:
                logger.warning(f"Conta não encontrada em cache: {account_id}")
        else:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache limpo: {count} credenciais removidas")
    
    def refresh_all(self) -> Dict[str, CachedCredential]:
        """
        Renova todas as credenciais em cache.
        
        Returns:
            Dict {account_id: CachedCredential} com credenciais renovadas
        
        Exemplo:
            cache = CredentialCacheManager(...)
            cache.assume_roles_for_all_accounts()
            
            # Depois de algum tempo...
            cache.refresh_all()
        """
        logger.info(f"Renovando {len(self._cache)} credenciais...")
        
        account_ids = list(self._cache.keys())
        account_names = {aid: self._cache[aid].account_name for aid in account_ids}
        
        return self.assume_roles_for_accounts(account_ids, account_names)
    
    def get_statistics(self) -> Dict:
        """
        Retorna estatísticas do cache.
        
        Returns:
            Dict com estatísticas
        
        Exemplo:
            cache = CredentialCacheManager(...)
            stats = cache.get_statistics()
            print(f"Total: {stats['total']}, Expiradas: {stats['expired']}")
        """
        total = len(self._cache)
        expired = sum(1 for cred in self._cache.values() if cred.is_expired())
        valid = total - expired
        
        return {
            'total': total,
            'valid': valid,
            'expired': expired,
            'security_account': self._base_identity['Account'],
            'role_name': self.role_name,
            'region': self.region
        }
    
    def __len__(self) -> int:
        """Retorna número de credenciais em cache."""
        return len(self._cache)
    
    def __contains__(self, account_id: str) -> bool:
        """Verifica se uma conta está em cache."""
        return account_id in self._cache
    
    def __str__(self) -> str:
        """Representação string."""
        return f"CredentialCacheManager(cached={len(self._cache)}, role={self.role_name})"
    
    def __repr__(self) -> str:
        """Representação detalhada."""
        stats = self.get_statistics()
        return (
            f"CredentialCacheManager("
            f"security_account={stats['security_account']}, "
            f"role={self.role_name}, "
            f"cached={stats['total']}, "
            f"valid={stats['valid']}, "
            f"expired={stats['expired']}"
            f")"
        )
