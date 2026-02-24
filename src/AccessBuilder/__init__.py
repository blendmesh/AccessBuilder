"""
AccessBuilder Client Manager Library - Módulo de gerenciamento de clientes AWS reutilizável

Fornece:
  - AWSClientManager: Classe para gerenciar clientes AWS
  - ConfigLoader: Carregador de credenciais
  - AWSCredentials: Dataclass para armazenar credenciais

Exemplo de uso:
    from AccessBuilder import AWSClientManager, ConfigLoader
    
    # Opção 1: Com arquivo .env
    config = ConfigLoader()
    creds = config.get_credentials_iam_user()
    manager = AWSClientManager(**creds.to_dict())
    
    # Opção 2: Com parâmetros diretos
    manager = AWSClientManager(
        region='us-east-1',
        aws_access_key_id='AKIA...',
        aws_secret_access_key='...'
    )
    
    manager.initialize()
    s3 = manager.s3_client
    s3.put_object(Bucket='bucket', Key='file', Body=b'data')
"""

__version__ = '1.1.0'
__author__ = 'AWS Client Manager Team'
__license__ = 'MIT'

from .aws_client import AWSClientManager
from .config import ConfigLoader, AWSCredentials
from .sso_auth import SSOAuthStrategy
from .organizations import OrganizationsHelper
from .credential_cache import CredentialCacheManager, CachedCredential

__all__ = [
    'AWSClientManager',
    'ConfigLoader', 
    'AWSCredentials',
    'SSOAuthStrategy',
    'OrganizationsHelper',
    'CredentialCacheManager',
    'CachedCredential',
]
