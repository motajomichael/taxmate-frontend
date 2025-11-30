import requests
from typing import Optional, Dict, Any, Tuple
import os


class APIClient:
    """
    Simple wrapper around your Node backend APIs.
    """

    def __init__(self, base_url: str | None = None):
        if base_url is None:
            base_url = os.environ.get("TAXMATE_API_BASE_URL", "http://localhost:4000/api")
        self.base_url = base_url.rstrip("/")

    def _headers(self, access_token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    # -------- Auth --------

    def register(self, email: str, password: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/auth/register"
        payload = {"email": email, "password": password}

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def login(self, email: str, password: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/auth/login"
        payload = {"email": email, "password": password}

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    # -------- Profile --------

    def get_profile(self, access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/profile"
        try:
            resp = requests.get(url, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def update_profile(self, data: Dict[str, Any], access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/profile"
        try:
            resp = requests.put(url, json=data, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    # -------- History --------

    def list_calculations(self, access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/calculations"
        try:
            resp = requests.get(url, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def get_calculation(self, calc_id: str, access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/calculations/{calc_id}"
        try:
            resp = requests.get(url, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    # -------- Hustle (Business & Transactions) --------

    def list_hustles(self, access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles"
        try:
            resp = requests.get(url, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def create_hustle(self, data: Dict[str, Any], access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles"
        try:
            resp = requests.post(url, json=data, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def list_hustle_transactions(
        self,
        hustle_id: str,
        access_token: str,
        limit: int = 50
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles/{hustle_id}/transactions"
        params = {"limit": limit}
        try:
            resp = requests.get(url, params=params, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def add_hustle_transaction(
        self,
        hustle_id: str,
        data: Dict[str, Any],
        access_token: str
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles/{hustle_id}/transactions"
        try:
            resp = requests.post(url, json=data, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def hustle_summary(
        self,
        hustle_id: str,
        access_token: str,
        params: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles/{hustle_id}/summary"
        try:
            resp = requests.get(url, params=params, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}
        
    
    def confirm_statement(
        self,
        hustle_id: str,
        statement_id: str,
        data: Dict[str, Any],
        access_token: str
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles/{hustle_id}/statements/{statement_id}/confirm"
        try:
            resp = requests.post(url, json=data, headers=self._headers(access_token), timeout=30)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    # -------- Hustle statement imports --------

    def import_statement(
        self,
        hustle_id: str,
        data: Dict[str, Any],
        access_token: str
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles/{hustle_id}/statements/import"
        try:
            resp = requests.post(url, json=data, headers=self._headers(access_token), timeout=30)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def get_statement_rows(
        self,
        hustle_id: str,
        statement_id: str,
        access_token: str
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/me/hustles/{hustle_id}/statements/{statement_id}/rows"
        try:
            resp = requests.get(url, headers=self._headers(access_token), timeout=30)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    # -------- Calculators --------

    def quick_pit(self, data: Dict[str, Any]) -> Tuple[bool, Any]:
        url = f"{self.base_url}/calc/quick-pit"
        try:
            resp = requests.post(url, json=data, timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def self_employed_quick(self, data: Dict[str, Any]) -> Tuple[bool, Any]:
        url = f"{self.base_url}/calc/self-employed-quick"
        try:
            resp = requests.post(url, json=data, timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def pit(self, data: Dict[str, Any], access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/calc/pit"
        try:
            resp = requests.post(url, json=data, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}

    def paye(self, data: Dict[str, Any], access_token: str) -> Tuple[bool, Any]:
        url = f"{self.base_url}/calc/paye"
        try:
            resp = requests.post(url, json=data, headers=self._headers(access_token), timeout=10)
            if resp.status_code >= 400:
                return False, resp.json()
            return True, resp.json()
        except Exception as e:
            return False, {"error": str(e)}
