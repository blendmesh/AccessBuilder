"""
config.py - Gerenciamento de Configurações e Credenciais AWS

Fornece classes para carregar configurações do ambiente e criar
instâncias do AWSClientManager automaticamente.

Uso:
    from AccessBuilder import ConfigLoader
    
    config = ConfigLoader('.env')
    manager = config.get_manager('us-east-1')
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class AWSCredentials:
    """Armazena credenciais AWS de forma segura."""
    
    region: str
    cross_account_role: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_session_token: Optional[str] = None
    sso_profile: Optional[str] = None
    external_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Converte credenciais para dicionário."""
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    def __str__(self) -> str:
        """Representação string (sem expor secrets)."""
        parts = [f"region={self.region}"]
        if self.sso_profile:
            parts.append(f"sso_profile={self.sso_profile}")
        if self.cross_account_role:
            parts.append(f"role={self.cross_account_role}")
        if self.external_id:
            parts.append(f"external_id={self.external_id[:8]}...")
        if self.aws_access_key_id:
            # Mostrar apenas primeiros e últimos 4 chars
            key = self.aws_access_key_id
            parts.append(f"key={key[:4]}...{key[-4:]}" if len(key) > 8 else "key=****")
        return f"AWSCredentials({', '.join(parts)})"


class ConfigLoader:
    """
    Carrega configurações AWS do ambiente (.env ou variáveis de ambiente).
    
    Formato esperado no .env:
        AWS_REGION=us-east-1
        AWS_ACCESS_KEY_ID=AKIA...
        AWS_SECRET_ACCESS_KEY=wJalr...
        # Para credenciais temporárias (STS):
        AWS_SESSION_TOKEN=FwoG...
        # Para cross-account:
        AWS_CROSS_ACCOUNT_ROLE=arn:aws:iam::123456789012:role/RoleName
    """
    
    def __init__(self, env_path: Optional[str] = None):
        """
        Inicializa ConfigLoader.
        
        Args:
            env_path: Caminho para arquivo .env (opcional)
                      Se não fornecido, usa variáveis de ambiente do sistema
        
        Exemplo:
            # Carregar do .env
            config = ConfigLoader('.env')
            
            # Carregar de variáveis de ambiente
            config = ConfigLoader()
        """
        self.env_path = env_path
        
        # Carregar arquivo .env se fornecido
        if env_path:
            self._load_env_file(env_path)
        
        logger.info(f"ConfigLoader inicializado (env_path={env_path})")
    
    def _load_env_file(self, env_path: str) -> None:
        """
        Carrega arquivo .env e define variáveis de ambiente.
        
        Args:
            env_path: Caminho para arquivo .env
        """
        path = Path(env_path)
        
        if not path.exists():
            logger.warning(f"Arquivo .env não encontrado: {env_path}")
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                # Ignorar comentários e linhas vazias
                if not line or line.startswith('#'):
                    continue
                
                # Parsear KEY=VALUE
                if '=' not in line:
                    continue
                
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Remover aspas se presentes
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                # Definir como variável de ambiente
                os.environ[key] = value
        
        logger.info(f"Arquivo .env carregado: {env_path}")
    
    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Obtém valor de variável de ambiente.
        
        Args:
            key: Nome da variável
            default: Valor padrão se não encontrado
        
        Returns:
            Valor da variável ou default
        """
        return os.getenv(key, default)
    
    def get_credentials(self, strategy: str = 'auto') -> AWSCredentials:
        """
        Cria objeto AWSCredentials baseado no ambiente.
        
        Estratégias:
            'auto': Detecta automaticamente baseado nas variáveis presentes
            'sso': Usa perfil SSO
            'provided': Usa credenciais fornecidas (access_key + secret_key)
            'temporary': Usa credenciais temporárias (com session_token)
            'cross_account': Usa cross-account role
            'default': Usa credenciais padrão (IAM role)
        
        Args:
            strategy: Estratégia de autenticação
        
        Returns:
            AWSCredentials: Objeto com credenciais configuradas
        
        Exemplo:
            config = ConfigLoader('.env')
            
            # Detectar automaticamente
            creds = config.get_credentials()
            
            # Forçar estratégia específica
            creds = config.get_credentials('temporary')
            
            # Usar com AWSClientManager
            from AccessBuilder import AWSClientManager
            manager = AWSClientManager(**asdict(creds))
            manager.initialize()
        """
        region = self.get_env('AWS_REGION', 'us-east-1')
        external_id = self.get_env('AWS_EXTERNAL_ID')
        
        if strategy == 'auto':
            # Detectar automaticamente
            sso_profile = self.get_env('AWS_PROFILE')
            access_key = self.get_env('AWS_ACCESS_KEY_ID')
            secret_key = self.get_env('AWS_SECRET_ACCESS_KEY')
            session_token = self.get_env('AWS_SESSION_TOKEN')
            cross_account = self.get_env('AWS_CROSS_ACCOUNT_ROLE')
            
            # Prioridade 1: SSO Profile
            if sso_profile:
                strategy = 'sso'
            # Prioridade 2: Cross-account role
            elif cross_account:
                strategy = 'cross_account'
            # Prioridade 3: Credenciais fornecidas
            elif access_key and secret_key:
                if session_token:
                    strategy = 'temporary'
                else:
                    strategy = 'provided'
            # Prioridade 4: Default
            else:
                strategy = 'default'
            
            logger.info(f"Estratégia detectada: {strategy}")
        
        if strategy == 'sso':
            return AWSCredentials(
                region=region,
                sso_profile=self.get_env('AWS_PROFILE'),
                external_id=external_id
            )
        
        elif strategy == 'provided':
            return AWSCredentials(
                region=region,
                aws_access_key_id=self.get_env('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=self.get_env('AWS_SECRET_ACCESS_KEY'),
                external_id=external_id
            )
        
        elif strategy == 'temporary':
            return AWSCredentials(
                region=region,
                aws_access_key_id=self.get_env('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=self.get_env('AWS_SECRET_ACCESS_KEY'),
                aws_session_token=self.get_env('AWS_SESSION_TOKEN'),
                external_id=external_id
            )
        
        elif strategy == 'cross_account':
            return AWSCredentials(
                region=region,
                cross_account_role=self.get_env('AWS_CROSS_ACCOUNT_ROLE'),
                external_id=external_id
            )
        
        else:  # default
            return AWSCredentials(region=region)
    
    def get_manager(self, strategy: str = 'auto'):
        """
        Cria instância do AWSClientManager configurado.
        
        Args:
            strategy: Estratégia de autenticação (default: 'auto')
        
        Returns:
            AWSClientManager: Gerenciador configurado e inicializado
        
        Exemplo:
            config = ConfigLoader('.env')
            manager = config.get_manager()  # Detecta automaticamente
            
            # Usar manager
            s3 = manager.s3_client
            buckets = s3.list_buckets()
        """
        from AccessBuilder import AWSClientManager
        
        creds = self.get_credentials(strategy)
        manager = AWSClientManager(**creds.to_dict())
        manager.initialize()
        
        logger.info(f"AWSClientManager criado: {creds}")
        
        return manager
