import sys
import json
from typing import List, Dict, Optional
from saxo_openapi.definitions.orders import AssetType
from saxo_openapi.endpoints.referencedata import instruments as rd_instruments
from saxo_openapi.exceptions import OpenAPIError
from elpis.config import settings


def instrument_to_uic(
    client,
    spec: Dict[str, str],
    assettype: Optional[str] = None,
    debug: bool = False,
    printout: bool = False
) -> List[Dict[str, Optional[str]]]:
    """
    Fetch instruments matching the given spec from the Saxo API.

    If assettype is None, performs a full search across all AssetTypes.

    Args:
        client: Saxo API client instance.
        spec: Dict containing 'Instrument' key with search keyword.
        assettype: Specific AssetType to filter by, or None for full search.
        debug: If True, print debug information to stderr.
        printout: If True, print fetched counts to stdout.

    Returns:
        List of dicts with keys: Uic, AssetType, Symbol,
        ExchangeId, IssuerCountry, Description, CurrencyCode.
    """
    # Determine asset types
    all_types = list(AssetType().definitions.keys())
    if assettype is None:
        types_to_search = all_types
        if debug:
            print("Performing full search across all asset types", file=sys.stderr)
    else:
        if assettype not in all_types:
            raise ValueError(f"Invalid assettype: {assettype}")
        types_to_search = [assettype]

    # Validate spec
    keyword = spec.get('Instrument')
    if not keyword:
        raise KeyError("spec must include non-empty 'Instrument' key")

    # Credentials
    access_token = settings.access_token

    results: List[Dict[str, Optional[str]]] = []
    for at in types_to_search:
        params = {
            # 'AccountKey': settings.account_key,
            'AccessToken': access_token,
            'AssetTypes': at,
            'Keywords': keyword
        }
        request = rd_instruments.Instruments(params=params)
        if debug:
            endpoint = getattr(request, 'ENDPOINT', '')
            print(f"🔗 Request endpoint: {endpoint}, params: {params}", file=sys.stderr)
        try:
            response = client.request(request)
        except OpenAPIError as e:
            if debug:
                print(f"Error fetching AssetType '{at}': {e}", file=sys.stderr)
            continue

        data = response.get('Data', []) or []
        if printout:
            print(f"Fetched {len(data)} items for AssetType '{at}'")
            print()
        for item in data:
            results.append({
                'Uic': item.get('Identifier'),
                'AssetType': item.get('AssetType'),
                'Symbol': item.get('Symbol'),
                'ExchangeId': item.get('ExchangeId'),
                'IssuerCountry': item.get('IssuerCountry'),
                'Description': item.get('Description'),
                'CurrencyCode': item.get('CurrencyCode')
            })
    return results
