from openai import OpenAI
import httpx

keys = {
    'A': 'AQ.Ab8RN6JV8MvBCaofPMymawNna9_7YdohiO4iM276H02iuiXn-Q',
    'B': 'AIzaSyCVej9gACgAkpYuIv0d0ETYnZuv52BpMLE',
    'C': 'AQ.Ab8RN6LPcQs1X3bjNV729TdgURM7trFB_b0KOfqAScsZxBUoDQ'
}

for name, key in keys.items():
    try:
        client = OpenAI(
            api_key=key,
            base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
            http_client=httpx.Client(timeout=10)
        )
        response = client.models.list()
        print(f"Key {name}: Working (Models found: {len(response.data)})")
    except Exception as e:
        print(f"Key {name}: FAILED - {str(e)[:100]}")
