"""
organizations.py - Helper para AWS Organizations

Fornece funcionalidades para descoberta automática de contas AWS
via AWS Organizations, incluindo filtros por OU (Organizational Unit).

Uso:
    from AccessBuilder.organizations import OrganizationsHelper
    
    org = OrganizationsHelper(session)
    accounts = org.list_all_accounts()
    prod_accounts = org.filter_by_ou(['Production'])
"""

import boto3
from botocore.exceptions import ClientError
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OrganizationsHelper:
    """
    Helper para trabalhar com AWS Organizations.
    
    Funcionalidades:
    - Listar todas as contas da organização
    - Filtrar contas por OU (Organizational Unit)
    - Obter hierarquia de OUs
    - Descobrir qual OU uma conta pertence
    
    Pré-requisitos:
    - Credenciais com permissões organizations:List*
    - Normalmente requer Management Account ou delegação administrativa
    """
    
    def __init__(self, session: boto3.Session = None):
        """
        Inicializa o OrganizationsHelper.
        
        Args:
            session: Sessão boto3. Se None, usa sessão default.
            
        Raises:
            ClientError: Se não tiver acesso ao Organizations
            
        Exemplo:
            # Com sessão específica
            session = boto3.Session(profile_name='management')
            org = OrganizationsHelper(session)
            
            # Com sessão default
            org = OrganizationsHelper()
        """
        self.session = session or boto3.Session()
        
        try:
            self.org_client = self.session.client('organizations')
            
            # Testa acesso ao Organizations
            self.organization = self.org_client.describe_organization()['Organization']
            
            logger.info(f"✅ Conectado ao AWS Organizations")
            logger.info(f"   Organization ID: {self.organization['Id']}")
            logger.info(f"   Master Account: {self.organization['MasterAccountId']}")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'AccessDeniedException':
                error_msg = (
                    "Sem permissão para acessar AWS Organizations. "
                    "Certifique-se de estar na Management Account ou ter "
                    "delegação administrativa para Organizations."
                )
                logger.error(f"❌ {error_msg}")
                raise ClientError(
                    {'Error': {'Code': 'AccessDeniedException', 'Message': error_msg}},
                    'DescribeOrganization'
                ) from e
            
            elif error_code == 'AWSOrganizationsNotInUseException':
                error_msg = (
                    "AWS Organizations não está habilitado nesta conta. "
                    "Habilite Organizations primeiro."
                )
                logger.error(f"❌ {error_msg}")
                raise ClientError(
                    {'Error': {'Code': 'OrganizationsNotEnabled', 'Message': error_msg}},
                    'DescribeOrganization'
                ) from e
            
            else:
                logger.error(f"❌ Erro ao acessar Organizations: {e}")
                raise
    
    def list_all_accounts(self, status: str = 'ACTIVE') -> List[Dict]:
        """
        Lista todas as contas da organização.
        
        Args:
            status: Filtro de status. Opções:
                   - 'ACTIVE': Apenas contas ativas (padrão)
                   - 'SUSPENDED': Apenas contas suspensas
                   - None: Todas as contas
        
        Returns:
            Lista de dicts com informações das contas:
                - Id: ID da conta (12 dígitos)
                - Name: Nome da conta
                - Email: Email da conta
                - Status: Status (ACTIVE/SUSPENDED)
                - JoinedTimestamp: Data de entrada na organização
                - Arn: ARN da conta
        
        Exemplo:
            org = OrganizationsHelper()
            accounts = org.list_all_accounts()
            
            for account in accounts:
                print(f"{account['Name']}: {account['Id']}")
        """
        logger.info(f"Listando contas do Organizations (status={status})...")
        
        accounts = []
        paginator = self.org_client.get_paginator('list_accounts')
        
        try:
            for page in paginator.paginate():
                for account in page['Accounts']:
                    # Aplicar filtro de status
                    if status is None or account['Status'] == status:
                        accounts.append({
                            'Id': account['Id'],
                            'Name': account['Name'],
                            'Email': account['Email'],
                            'Status': account['Status'],
                            'JoinedTimestamp': account.get('JoinedTimestamp'),
                            'Arn': account['Arn']
                        })
            
            logger.info(f"✅ Encontradas {len(accounts)} contas")
            return accounts
            
        except ClientError as e:
            logger.error(f"❌ Erro ao listar contas: {e}")
            raise
    
    def list_organizational_units(self, parent_id: Optional[str] = None) -> List[Dict]:
        """
        Lista OUs (Organizational Units).
        
        Args:
            parent_id: ID do parent. Se None, usa root da organização.
        
        Returns:
            Lista de dicts com informações das OUs:
                - Id: ID da OU
                - Name: Nome da OU
                - Arn: ARN da OU
        
        Exemplo:
            org = OrganizationsHelper()
            ous = org.list_organizational_units()
            
            for ou in ous:
                print(f"{ou['Name']}: {ou['Id']}")
        """
        if parent_id is None:
            # Obtém o root ID
            roots = self.org_client.list_roots()['Roots']
            parent_id = roots[0]['Id']
            logger.debug(f"Usando Organization Root: {parent_id}")
        
        logger.info(f"Listando OUs sob parent: {parent_id}")
        
        ous = []
        paginator = self.org_client.get_paginator('list_organizational_units_for_parent')
        
        try:
            for page in paginator.paginate(ParentId=parent_id):
                for ou in page['OrganizationalUnits']:
                    ous.append({
                        'Id': ou['Id'],
                        'Name': ou['Name'],
                        'Arn': ou['Arn']
                    })
            
            logger.info(f"✅ Encontradas {len(ous)} OUs")
            return ous
            
        except ClientError as e:
            logger.error(f"❌ Erro ao listar OUs: {e}")
            raise
    
    def list_accounts_for_ou(self, ou_id: str) -> List[Dict]:
        """
        Lista contas dentro de uma OU específica.
        
        Args:
            ou_id: ID da OU (formato: 'ou-xxxx-yyyyyyyy')
        
        Returns:
            Lista de contas na OU
        
        Exemplo:
            org = OrganizationsHelper()
            accounts = org.list_accounts_for_ou('ou-xxxx-12345678')
            print(f"Contas na OU: {len(accounts)}")
        """
        logger.info(f"Listando contas na OU: {ou_id}")
        
        accounts = []
        paginator = self.org_client.get_paginator('list_accounts_for_parent')
        
        try:
            for page in paginator.paginate(ParentId=ou_id):
                for account in page['Accounts']:
                    if account['Status'] == 'ACTIVE':
                        accounts.append({
                            'Id': account['Id'],
                            'Name': account['Name'],
                            'Email': account['Email'],
                            'Status': account['Status']
                        })
            
            logger.info(f"✅ Encontradas {len(accounts)} contas na OU")
            return accounts
            
        except ClientError as e:
            logger.error(f"❌ Erro ao listar contas da OU: {e}")
            raise
    
    def filter_by_ou(self, ou_names: List[str]) -> List[Dict]:
        """
        Filtra contas por nomes de OUs.
        
        Busca recursivamente em toda a hierarquia de OUs e retorna
        todas as contas que estão em OUs com os nomes especificados.
        
        Args:
            ou_names: Lista de nomes de OUs (case-insensitive)
        
        Returns:
            Lista de contas encontradas nas OUs especificadas
        
        Exemplo:
            org = OrganizationsHelper()
            
            # Buscar contas em Production e Development
            accounts = org.filter_by_ou(['Production', 'Development'])
            
            for account in accounts:
                print(f"{account['Name']}: {account['Id']}")
        """
        logger.info(f"Filtrando contas por OUs: {ou_names}")
        
        # Normalizar nomes para lowercase
        ou_names_set = set(name.lower() for name in ou_names)
        
        # Obter root
        roots = self.org_client.list_roots()['Roots']
        root_id = roots[0]['Id']
        
        matching_accounts = []
        
        def search_ous(parent_id: str):
            """Busca recursiva em OUs."""
            try:
                ous = self.list_organizational_units(parent_id)
                
                for ou in ous:
                    # Verifica se o nome da OU corresponde
                    if ou['Name'].lower() in ou_names_set:
                        logger.info(f"✅ OU encontrada: {ou['Name']} ({ou['Id']})")
                        
                        # Adiciona contas desta OU
                        accounts = self.list_accounts_for_ou(ou['Id'])
                        matching_accounts.extend(accounts)
                    
                    # Busca recursivamente em OUs filhas
                    search_ous(ou['Id'])
                    
            except Exception as e:
                logger.warning(f"Erro ao buscar OUs em {parent_id}: {e}")
        
        # Inicia busca recursiva
        search_ous(root_id)
        
        # Remove duplicatas (uma conta pode estar em múltiplas OUs encontradas)
        unique_accounts = []
        seen_ids = set()
        
        for account in matching_accounts:
            if account['Id'] not in seen_ids:
                unique_accounts.append(account)
                seen_ids.add(account['Id'])
        
        logger.info(f"✅ Total de {len(unique_accounts)} contas únicas encontradas")
        return unique_accounts
    
    def get_account_ou(self, account_id: str) -> Optional[Dict]:
        """
        Descobre em qual OU uma conta está localizada.
        
        Args:
            account_id: ID da conta
        
        Returns:
            Dict com informações da OU ou None se estiver na root
        
        Exemplo:
            org = OrganizationsHelper()
            ou = org.get_account_ou('123456789012')
            
            if ou:
                print(f"Conta está na OU: {ou['Name']}")
            else:
                print("Conta está na root")
        """
        try:
            parents = self.org_client.list_parents(ChildId=account_id)['Parents']
            
            if parents:
                parent = parents[0]  # Uma conta só tem um parent
                
                if parent['Type'] == 'ORGANIZATIONAL_UNIT':
                    ou = self.org_client.describe_organizational_unit(
                        OrganizationalUnitId=parent['Id']
                    )['OrganizationalUnit']
                    
                    return {
                        'Id': ou['Id'],
                        'Name': ou['Name'],
                        'Arn': ou['Arn']
                    }
            
            return None
            
        except ClientError as e:
            logger.error(f"❌ Erro ao obter OU da conta {account_id}: {e}")
            return None
    
    def get_organization_info(self) -> Dict:
        """
        Retorna informações sobre a organização.
        
        Returns:
            Dict com informações da organização
        """
        return {
            'Id': self.organization['Id'],
            'Arn': self.organization['Arn'],
            'MasterAccountId': self.organization['MasterAccountId'],
            'MasterAccountEmail': self.organization.get('MasterAccountEmail'),
            'FeatureSet': self.organization.get('FeatureSet', 'UNKNOWN')
        }
    
    def __str__(self) -> str:
        """Representação string."""
        return f"OrganizationsHelper(org_id={self.organization['Id']})"
    
    def __repr__(self) -> str:
        """Representação detalhada."""
        return (
            f"OrganizationsHelper("
            f"org_id={self.organization['Id']}, "
            f"master={self.organization['MasterAccountId']}"
            f")"
        )


# Exemplo de uso
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("=== Teste de OrganizationsHelper ===\n")
    
    try:
        # Inicializa
        org = OrganizationsHelper()
        
        print("1. Informações da Organização:")
        info = org.get_organization_info()
        print(f"   Organization ID: {info['Id']}")
        print(f"   Master Account: {info['MasterAccountId']}")
        
        print("\n2. Listando todas as contas:")
        accounts = org.list_all_accounts()
        for acc in accounts[:5]:  # Mostra apenas 5
            print(f"   - {acc['Name']} ({acc['Id']})")
        if len(accounts) > 5:
            print(f"   ... e mais {len(accounts) - 5} contas")
        
        print("\n3. Listando OUs:")
        ous = org.list_organizational_units()
        for ou in ous:
            print(f"   - {ou['Name']} ({ou['Id']})")
        
        if ous:
            print(f"\n4. Contas na OU '{ous[0]['Name']}':")
            ou_accounts = org.list_accounts_for_ou(ous[0]['Id'])
            for acc in ou_accounts[:3]:
                print(f"   - {acc['Name']} ({acc['Id']})")
        
        print("\n✅ Todos os testes passaram!")
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        print(f"\n❌ Erro: {error_code}")
        print(f"   {e.response['Error']['Message']}")
        
        if error_code == 'AccessDeniedException':
            print("\nNota: Execute com credenciais da Management Account")
    
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
