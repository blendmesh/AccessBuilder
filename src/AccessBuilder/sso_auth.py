"""
sso_auth.py - Autenticação via AWS IAM Identity Center (SSO)

Fornece estratégia de autenticação usando perfis SSO configurados
no AWS CLI (~/.aws/config).

Uso:
    from AccessBuilder.sso_auth import SSOAuthStrategy
    
    sso = SSOAuthStrategy(profile_name='my-sso-profile')
    session = sso.get_session()
    identity = sso.get_caller_identity()
"""

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SSOAuthStrategy:
    """
    Estratégia de autenticação via AWS IAM Identity Center (SSO).
    
    Características:
    - Usa perfis SSO configurados no ~/.aws/config
    - Suporta credenciais temporárias gerenciadas pelo AWS CLI
    - Verifica validade das credenciais
    - Fornece informações sobre expiração
    
    Pré-requisitos:
    1. AWS CLI instalado e configurado
    2. Perfil SSO configurado em ~/.aws/config
    3. Login realizado: aws sso login --profile <profile-name>
    
    Exemplo de configuração ~/.aws/config:
        [profile my-sso-profile]
        sso_start_url = https://my-org.awsapps.com/start
        sso_region = us-east-1
        sso_account_id = 123456789012
        sso_role_name = MyRole
        region = us-east-1
    """
    
    def __init__(self, profile_name: str):
        """
        Inicializa estratégia de autenticação SSO.
        
        Args:
            profile_name: Nome do perfil SSO configurado no ~/.aws/config
            
        Raises:
            ProfileNotFound: Se o perfil não existir
            NoCredentialsError: Se as credenciais SSO estiverem expiradas
            
        Exemplo:
            sso = SSOAuthStrategy(profile_name='security-account')
        """
        self.profile_name = profile_name
        self.session: Optional[boto3.Session] = None
        self._identity: Optional[Dict] = None
        
        logger.info(f"Inicializando SSOAuthStrategy com perfil: {profile_name}")
        
        # Valida perfil e credenciais
        self._validate_sso_credentials()
    
    def _validate_sso_credentials(self) -> None:
        """
        Valida se o perfil SSO existe e as credenciais estão válidas.
        
        Raises:
            ProfileNotFound: Se o perfil não existir
            NoCredentialsError: Se as credenciais SSO estiverem expiradas
            RuntimeError: Se houver outro erro de autenticação
        """
        try:
            # Tenta criar sessão com o perfil
            self.session = boto3.Session(profile_name=self.profile_name)
            
            # Testa credenciais fazendo uma chamada
            sts = self.session.client('sts')
            self._identity = sts.get_caller_identity()
            
            logger.info(f"✅ SSO autenticado com sucesso")
            logger.info(f"   Perfil: {self.profile_name}")
            logger.info(f"   ARN: {self._identity['Arn']}")
            logger.info(f"   Account: {self._identity['Account']}")
            
        except ProfileNotFound as e:
            error_msg = (
                f"Perfil SSO '{self.profile_name}' não encontrado. "
                f"Verifique ~/.aws/config"
            )
            logger.error(f"❌ {error_msg}")
            raise ProfileNotFound(profile=self.profile_name) from e
        
        except NoCredentialsError as e:
            error_msg = (
                f"Credenciais SSO expiradas ou não encontradas para o perfil '{self.profile_name}'. "
                f"Execute: aws sso login --profile {self.profile_name}"
            )
            logger.error(f"❌ {error_msg}")
            raise NoCredentialsError() from e
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['ExpiredToken', 'InvalidToken']:
                error_msg = (
                    f"Token SSO expirado para o perfil '{self.profile_name}'. "
                    f"Execute: aws sso login --profile {self.profile_name}"
                )
                logger.error(f"❌ {error_msg}")
                raise NoCredentialsError() from e
            else:
                logger.error(f"❌ Erro ao validar credenciais SSO: {e}")
                raise RuntimeError(f"Falha na autenticação SSO: {e}") from e
        
        except Exception as e:
            logger.error(f"❌ Erro inesperado ao validar SSO: {e}")
            raise RuntimeError(f"Erro ao inicializar SSO: {e}") from e
    
    def get_session(self) -> boto3.Session:
        """
        Retorna a sessão boto3 configurada com o perfil SSO.
        
        Returns:
            boto3.Session: Sessão configurada e autenticada
            
        Exemplo:
            sso = SSOAuthStrategy('my-profile')
            session = sso.get_session()
            s3 = session.client('s3')
        """
        if self.session is None:
            self._validate_sso_credentials()
        
        return self.session
    
    def get_caller_identity(self) -> Dict:
        """
        Retorna informações sobre a identidade AWS atual.
        
        Returns:
            Dict com chaves:
                - Account: ID da conta AWS
                - UserId: ID do usuário/role
                - Arn: ARN completo da identidade
        
        Exemplo:
            sso = SSOAuthStrategy('my-profile')
            identity = sso.get_caller_identity()
            print(f"Conectado como: {identity['Arn']}")
            print(f"Account: {identity['Account']}")
        """
        if self._identity is None:
            sts = self.get_session().client('sts')
            self._identity = sts.get_caller_identity()
        
        return self._identity
    
    def get_account_id(self) -> str:
        """
        Retorna o ID da conta AWS atual.
        
        Returns:
            str: ID da conta (12 dígitos)
        """
        return self.get_caller_identity()['Account']
    
    def get_user_arn(self) -> str:
        """
        Retorna o ARN da identidade atual.
        
        Returns:
            str: ARN completo
        """
        return self.get_caller_identity()['Arn']
    
    def test_connection(self) -> bool:
        """
        Testa se a conexão SSO está funcionando.
        
        Returns:
            bool: True se conectado, False caso contrário
        
        Exemplo:
            sso = SSOAuthStrategy('my-profile')
            if sso.test_connection():
                print("✅ SSO funcionando")
            else:
                print("❌ Problema com SSO")
        """
        try:
            identity = self.get_caller_identity()
            logger.info("✅ Teste de conexão SSO: OK")
            logger.debug(f"   Identidade: {identity['Arn']}")
            return True
        except Exception as e:
            logger.error(f"❌ Teste de conexão SSO: FALHOU - {e}")
            return False
    
    def get_credential_expiration(self) -> Optional[datetime]:
        """
        Tenta obter a data de expiração das credenciais SSO.
        
        Note: Esta informação pode não estar sempre disponível,
        dependendo de como as credenciais SSO foram obtidas.
        
        Returns:
            datetime: Data de expiração ou None se não disponível
        
        Exemplo:
            sso = SSOAuthStrategy('my-profile')
            expiry = sso.get_credential_expiration()
            if expiry:
                print(f"Credenciais expiram em: {expiry}")
            else:
                print("Expiração não disponível")
        """
        try:
            credentials = self.session.get_credentials()
            if hasattr(credentials, 'expiry_time') and credentials.expiry_time:
                logger.debug(f"Credenciais SSO expiram em: {credentials.expiry_time}")
                return credentials.expiry_time
            else:
                logger.debug("Informação de expiração não disponível")
                return None
        except Exception as e:
            logger.warning(f"Não foi possível obter expiração das credenciais: {e}")
            return None
    
    def refresh_credentials(self) -> None:
        """
        Força renovação das credenciais SSO.
        
        Note: O usuário precisa executar 'aws sso login' manualmente
        se as credenciais estiverem expiradas.
        
        Raises:
            NoCredentialsError: Se as credenciais não puderem ser renovadas
        """
        logger.info("Forçando renovação de credenciais SSO...")
        self.session = None
        self._identity = None
        self._validate_sso_credentials()
        logger.info("✅ Credenciais SSO renovadas")
    
    def __str__(self) -> str:
        """Representação string da estratégia."""
        return f"SSOAuthStrategy(profile={self.profile_name})"
    
    def __repr__(self) -> str:
        """Representação detalhada."""
        identity = self._identity or {}
        return (
            f"SSOAuthStrategy("
            f"profile={self.profile_name}, "
            f"account={identity.get('Account', 'unknown')}, "
            f"arn={identity.get('Arn', 'unknown')}"
            f")"
        )


def is_sso_profile(profile_name: str) -> bool:
    """
    Verifica se um perfil é do tipo SSO.
    
    Args:
        profile_name: Nome do perfil
        
    Returns:
        bool: True se for perfil SSO, False caso contrário
    
    Exemplo:
        if is_sso_profile('my-profile'):
            print("Este é um perfil SSO")
    """
    try:
        session = boto3.Session(profile_name=profile_name)
        # Perfis SSO geralmente têm configurações específicas
        # Podemos tentar detectar pelo formato das credenciais
        creds = session.get_credentials()
        
        # Credenciais SSO começam com ASIA (temporary)
        if creds and creds.access_key:
            return creds.access_key.startswith('ASIA')
        
        return False
    except Exception:
        return False


# Exemplo de uso
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=== Teste de SSOAuthStrategy ===\n")
    
    try:
        # Teste com perfil
        profile = 'security-account'  # Ajuste conforme seu perfil
        
        print(f"1. Testando perfil SSO: {profile}")
        sso = SSOAuthStrategy(profile_name=profile)
        
        print(f"\n2. Informações da conta:")
        identity = sso.get_caller_identity()
        print(f"   ARN: {identity['Arn']}")
        print(f"   Account: {identity['Account']}")
        print(f"   User ID: {identity['UserId']}")
        
        print(f"\n3. Teste de conexão:")
        if sso.test_connection():
            print("   ✅ Conexão OK")
        else:
            print("   ❌ Conexão FALHOU")
        
        print(f"\n4. Expiração de credenciais:")
        expiry = sso.get_credential_expiration()
        if expiry:
            print(f"   Expira em: {expiry}")
        else:
            print("   Informação não disponível")
        
        print(f"\n5. Usando sessão:")
        session = sso.get_session()
        s3 = session.client('s3')
        print(f"   Cliente S3 criado: {type(s3)}")
        
        print("\n✅ Todos os testes passaram!")
        
    except ProfileNotFound as e:
        print(f"\n❌ Perfil não encontrado: {e}")
        print(f"\nConfigure o perfil SSO em ~/.aws/config")
    
    except NoCredentialsError:
        print(f"\n❌ Credenciais SSO expiradas ou não encontradas")
        print(f"\nExecute: aws sso login --profile {profile}")
    
    except Exception as e:
        print(f"\n❌ Erro: {e}")
