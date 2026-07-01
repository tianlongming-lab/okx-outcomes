"""
OKX Outcomes API Client
环境变量: OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, OKX_AGENT_PRIVATE_KEY
"""
import os, base64, hashlib, hmac, json, time, secrets, logging, datetime
from typing import Optional, Callable, Dict, Any
from urllib.parse import urljoin
import httpx
import websockets
import msgpack
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("okx")

TESTNET = os.getenv("OKX_TESTNET", "false").lower() == "true"
BASE_URL = "https://www.okx.com" if not TESTNET else "https://testnet.okx.com"
WS_URL = "wss://ws.okx.com:8443/ws/v5/business" if not TESTNET else "wss://ws.okx.com:8443/ws/v5/business"
PROXY_URL = os.getenv("OKX_PROXY", "")
CHAIN_ID = int(os.getenv("OKX_CHAIN_ID", "196"))

# OKX Rust SDK EIP-712 domain: name="Exchange", version="1", chainId=70000196, verifyingContract=0x0
EIP712_DOMAIN_CHAIN_ID = 70000196
AGENT_SOURCE = "Mainnet" if not TESTNET else "Testnet"

try:
    from eth_account import Account
    from eth_utils import keccak
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False


def _gen_cloid(region=0, env=1) -> str:
    """Generate clientOrderId: 0x{region}{env}{30 hex rand}"""
    return f"0x{region:x}{env:x}{secrets.token_hex(15)}"

def _now_ms() -> int:
    return int(time.time() * 1000)

def _iso8601_timestamp() -> str:
    """Generate ISO 8601 timestamp: YYYY-MM-DDTHH:MM:SS.sssZ"""
    now = datetime.datetime.utcnow()
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'

def _hmac_sign(timestamp: str, method: str, path: str, body: str, secret: str) -> str:
    msg = timestamp + method + path + body
    mac = hmac.new(secret.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def _build_unsigned_tx_msgpack(action: dict, nonce: int, expires_after: int = None) -> bytes:
    """Build msgpack bytes matching rmp_serde::to_vec_named(UnsignedTransaction).

    Uses OrderedDict to match serde struct map encoding.
    Field order (load-bearing): action, nonce, expiresAfter?, user?
    """
    from collections import OrderedDict
    tx = OrderedDict()
    tx["action"] = action
    tx["nonce"] = nonce
    if expires_after is not None:
        tx["expiresAfter"] = expires_after
    return msgpack.packb(tx)


def _eip712_sign(action: dict, nonce: int, agent_key_hex: str, expires_after: int = None) -> Optional[dict]:
    """Sign action via OKX Agent-based EIP-712.

    Flow:
      1. msgpack(UnsignedTransaction) → bytes
      2. keccak256(bytes) → connectionId
      3. EIP-712 sign Agent {source, connectionId} with domain {Exchange, v1, 70000196, 0x0}

    Returns {Ecdsa: {r, s, v}} or None.
    """
    if not agent_key_hex or agent_key_hex.startswith("your_"):
        logger.warning("No valid agent key – EIP-712 signing skipped")
        return None
    if not HAS_ETH_ACCOUNT:
        logger.warning("eth_account not installed – install with: pip install eth-account")
        return None
    try:
        if agent_key_hex.startswith("0x"):
            agent_key_hex = agent_key_hex[2:]
        acct = Account.from_key(bytes.fromhex(agent_key_hex))

        msgpack_bytes = _build_unsigned_tx_msgpack(action, nonce, expires_after)
        conn_id = keccak(msgpack_bytes)

        full_message = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Agent": [
                    {"name": "source", "type": "string"},
                    {"name": "connectionId", "type": "bytes32"},
                ],
            },
            "primaryType": "Agent",
            "domain": {
                "name": "Exchange",
                "version": "1",
                "chainId": EIP712_DOMAIN_CHAIN_ID,
                "verifyingContract": "0x0000000000000000000000000000000000000000",
            },
            "message": {
                "source": AGENT_SOURCE,
                "connectionId": "0x" + conn_id.hex(),
            },
        }

        signed = acct.sign_typed_data(full_message=full_message)
        r_hex = "0x" + signed.r.to_bytes(32, 'big').hex()
        s_hex = "0x" + signed.s.to_bytes(32, 'big').hex()
        v = signed.v - 27  # OKX SDK expects 0..1 recovery ID

        logger.info(
            "EIP-712 Agent sign: addr=%s source=%s connId=0x%s... r=%s... s=%s... v=%d",
            acct.address, AGENT_SOURCE, conn_id.hex()[:8],
            r_hex[:20], s_hex[:20], v,
        )
        return {"Ecdsa": {"r": r_hex, "s": s_hex, "v": v}}
    except Exception as e:
        import traceback
        logger.error("EIP-712 sign error: %s", e)
        logger.error("Traceback: %s", traceback.format_exc())
        return None


def _get_eip712_agent_types_and_message(source: str, connection_id_hex: str) -> tuple:
    """Return EIP-712 types dict and message for Agent struct (debug use)."""
    types = {
        "Agent": [
            {"name": "source", "type": "string"},
            {"name": "connectionId", "type": "bytes32"},
        ],
    }
    msg = {"source": source, "connectionId": "0x" + connection_id_hex}
    return types, msg


class OkxClient:
    def __init__(self):
        self.ak = os.getenv("OKX_API_KEY", "")
        self.sk = os.getenv("OKX_SECRET_KEY", "")
        self.pp = os.getenv("OKX_PASSPHRASE", "")
        self.agent = os.getenv("OKX_AGENT_PRIVATE_KEY", "")
        self._http: Optional[httpx.AsyncClient] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_callbacks: Dict[str, Callable[[dict], None]] = {}
        self._ws_subscriptions: set = set()
        self._ws_running: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.ak and self.sk and self.pp)

    @property
    def can_sign(self) -> bool:
        return bool(self.agent and not self.agent.startswith("your_"))

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            proxy_settings = {"proxy": PROXY_URL} if PROXY_URL else {}
            self._http = httpx.AsyncClient(timeout=15.0, verify=False, **proxy_settings)
        return self._http

    # ── WebSocket ──
    async def ws_connect(self) -> bool:
        """Connect to WebSocket server"""
        if self._ws is not None:
            return True
        try:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self._ws = await websockets.connect(WS_URL, ping_interval=20, ping_timeout=60, ssl=ssl_context, proxy=PROXY_URL)
            self._ws_running = True
            logger.info("✅ WebSocket connected")
            await self._ws_auth()
            return True
        except Exception as e:
            logger.error(f"WebSocket connect failed: {e}")
            self._ws = None
            return False

    async def _ws_auth(self):
        """Authenticate WebSocket connection"""
        if not self.configured:
            return
        ts = str(int(time.time()))
        sign = _hmac_sign(ts, "GET", "/users/self/verify", "", self.sk)
        auth_msg = {
            "op": "login",
            "args": [{
                "apiKey": self.ak,
                "passphrase": self.pp,
                "timestamp": ts,
                "sign": sign
            }]
        }
        await self._ws.send(json.dumps(auth_msg))

    async def ws_subscribe(self, channel: str, inst_id: str = None):
        """Subscribe to a WebSocket channel"""
        if self._ws is None:
            await self.ws_connect()
        sub_key = f"{channel}#{inst_id}" if inst_id else channel
        if sub_key in self._ws_subscriptions:
            return
        self._ws_subscriptions.add(sub_key)
        arg = {"channel": channel}
        if inst_id:
            arg["instId"] = inst_id
        msg = {"op": "subscribe", "args": [arg]}
        await self._ws.send(json.dumps(msg))
        logger.info(f"Subscribed to {channel}#{inst_id}")

    async def ws_unsubscribe(self, channel: str, inst_id: str = None):
        """Unsubscribe from a WebSocket channel"""
        if self._ws is None:
            return
        sub_key = f"{channel}#{inst_id}" if inst_id else channel
        if sub_key not in self._ws_subscriptions:
            return
        self._ws_subscriptions.remove(sub_key)
        await self._ws.send(json.dumps({"op": "unsubscribe", "args": [{"channel": channel, "instId": inst_id}]}))

    def ws_on(self, channel: str, callback: Callable[[dict], None]):
        """Register callback for a channel"""
        self._ws_callbacks[channel] = callback

    async def ws_listen(self):
        """Listen to WebSocket messages"""
        if self._ws is None:
            await self.ws_connect()
        while self._ws_running:
            try:
                msg = await self._ws.recv()
                data = json.loads(msg)
                channel = data.get("arg", {}).get("channel", "")
                if channel and channel in self._ws_callbacks:
                    self._ws_callbacks[channel](data)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                self._ws_running = False
                break
            except Exception as e:
                logger.error(f"WebSocket listen error: {e}")

    async def ws_disconnect(self):
        """Disconnect WebSocket"""
        self._ws_running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
            logger.info("WebSocket disconnected")

    # ── raw request ──
    async def _req(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
        if not self.configured:
            return {"code": -1, "message": "未配置API密钥，请设置环境变量 OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE", "data": None}
        client = await self._client()
        body_str = json.dumps(body) if body else ""
        ts = _iso8601_timestamp()
        from urllib.parse import urlencode
        full_path = path
        if params and method == "GET":
            full_path = f"{path}?{urlencode(sorted(params.items()))}"
        logger.info(f"DEBUG SIGN: ts={ts}, method={method}, path={full_path}, body={body_str[:50]}")
        sign = _hmac_sign(ts, method, full_path, body_str, self.sk)
        headers = {
            "OK-ACCESS-KEY": self.ak, "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self.pp,
            "Content-Type": "application/json"
        }
        url = urljoin(BASE_URL, full_path)
        try:
            if method == "GET":
                r = await client.get(url, headers=headers)
            else:
                r = await client.post(url, headers=headers, content=body_str)
            resp_json = r.json()
            print(f"[DEBUG HTTP] Status: {r.status_code}, Body: {json.dumps(resp_json)[:400]}")
            return resp_json
        except httpx.HTTPError as e:
            return {"code": -1, "message": f"HTTP: {e}", "data": None}
        except Exception as e:
            return {"code": -1, "message": str(e), "data": None}

    async def _signed_post(self, path: str, action: dict, extra: dict = None, sign_action: dict = None) -> dict:
        """POST with EIP-712 signature.
        `action`     – JSON body action.
        `sign_action`– EIP-712 signing action (defaults to `action`).
        """
        nonce = _now_ms()
        sa = sign_action or action
        need_expires = sa.get("type") in ("cancelAll", "heartbeat")
        expires_after = _now_ms() + (300000 if need_expires else 3600000)
        sig = _eip712_sign(sa, nonce, agent_key_hex=self.agent,
                           expires_after=expires_after if need_expires else None)
        if sig is None:
            return {"code": -1, "message": "签名失败：请安装 eth-account 并配置 OKX_AGENT_PRIVATE_KEY", "data": None}
        body = {"action": action, "nonce": nonce, "signature": sig}
        if need_expires:
            body["expiresAfter"] = expires_after
        if extra:
            body.update({k: v for k, v in extra.items()})
        full_body = json.dumps(body)
        print(f"[DEBUG] SIGNED POST BODY: {full_body}")
        logger.info(f"DEBUG SIGNED POST: path={path}, body={full_body[:200]}")
        return await self._req("POST", path, body=body)

    # ── Events & Markets ──
    async def get_events(self, status="active", sort="volume_24h", cursor=None, page_size=20) -> dict:
        p = {"status": status, "sort": sort, "pageSize": str(page_size)}
        if cursor: p["cursor"] = cursor
        return await self._req("GET", "/api/v5/predictions/events", params=p)

    async def get_event(self, event_id: str) -> dict:
        return await self._req("GET", f"/api/v5/predictions/events/{event_id}")

    async def get_event_markets(self, event_id: str) -> dict:
        return await self._req("GET", f"/api/v5/predictions/events/{event_id}/markets")

    async def get_market(self, market_id: str) -> dict:
        return await self._req("GET", f"/api/v5/predictions/markets/{market_id}")

    async def search_events(self, keyword: str, cursor=None, page_size=20) -> dict:
        p = {"keyword": keyword, "pageSize": str(page_size)}
        if cursor: p["cursor"] = cursor
        return await self._req("GET", "/api/v5/predictions/events/search", params=p)

    # ── Market Data ──
    async def get_ticker(self, inst_id: str) -> dict:
        return await self._req("GET", "/api/v5/market/ticker", params={"instId": inst_id})

    async def get_candles(self, inst_id: str, bar="1H", limit=100, before=None, after=None) -> dict:
        p = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if before: p["before"] = before
        if after: p["after"] = after
        return await self._req("GET", "/api/v5/market/candles", params=p)

    async def get_orderbook(self, inst_id: str, sz=20) -> dict:
        return await self._req("GET", "/api/v5/market/pm-books", params={"instId": inst_id, "sz": str(sz)})

    async def get_public_trades(self, inst_id: str, limit=50) -> dict:
        return await self._req("GET", "/api/v5/market/trades", params={"instId": inst_id, "limit": str(limit)})

    # ── Orders ──
    async def list_orders(self, market_id=None, status="open", cursor=None, limit=50) -> dict:
        p = {"status": status, "limit": str(limit)}
        if market_id: p["marketId"] = market_id
        if cursor: p["cursor"] = cursor
        return await self._req("GET", "/api/v5/predictions/orders", params=p)

    async def get_order(self, order_id: str) -> dict:
        return await self._req("GET", f"/api/v5/predictions/orders/{order_id}")

    async def place_order(self, asset_id: str, side: str, price: str, size: str,
                          size_type="BASE", tif="GTC", reduce_only=False) -> dict:
        cloid = _gen_cloid()
        side_lower = side.lower()
        tif_lower = tif.lower()
        size_type_lower = size_type.lower() if size_type else "base"
        
        order_type_struct = {"limit": {"tif": tif_lower}}
        
        sign_order = [
            ("assetId", asset_id),
            ("side", side_lower),
            ("marketType", "prediction"),
            ("clientOrderId", cloid),
            ("price", price),
            ("reduceOnly", reduce_only),
            ("size", size),
        ]
        if size_type_lower == "quote":
            sign_order.append(("sizeType", "quote"))
        sign_order.append(("orderType", order_type_struct))
        
        body_order = {
            "assetId": asset_id,
            "marketType": "prediction",
            "side": side_lower,
            "price": price,
            "size": size,
            "clientOrderId": cloid,
            "orderType": order_type_struct,
        }
        if size_type_lower == "quote":
            body_order["sizeType"] = "quote"
        if reduce_only:
            body_order["reduceOnly"] = True
        
        from collections import OrderedDict
        sign_action = OrderedDict()
        sign_action["type"] = "placeOrder"
        sign_action["grouping"] = "na"
        sign_action["orders"] = [OrderedDict(sign_order)]
        body_action = OrderedDict()
        body_action["type"] = "placeOrder"
        body_action["grouping"] = "na"
        body_action["orders"] = [body_order]
        return await self._signed_post("/api/v5/predictions/orders", body_action, sign_action=sign_action)

    async def cancel_order(self, asset_id: str, order_id: str, is_cloid: bool = False) -> dict:
        from collections import OrderedDict
        cancel_item = OrderedDict()
        cancel_item["assetId"] = asset_id
        cancel_item["marketType"] = "prediction"
        if is_cloid:
            cancel_item["clientOrderId"] = order_id
        else:
            cancel_item["oid"] = order_id
        action = OrderedDict()
        action["type"] = "cancel"
        action["cancels"] = [cancel_item]
        return await self._signed_post("/api/v5/predictions/orders/cancel", action)

    async def cancel_all(self, asset_ids: list = None) -> dict:
        from collections import OrderedDict
        ids = asset_ids if asset_ids else []
        action = OrderedDict()
        action["type"] = "cancelAll"
        action["assetIds"] = ids
        action["marketType"] = "prediction"
        return await self._signed_post("/api/v5/predictions/orders/cancel-all", action)

    # ── Account ──
    async def get_balance(self) -> dict:
        return await self._req("GET", "/api/v5/predictions/balance")

    async def get_positions(self, status="open", market_id=None, cursor=None, limit=50) -> dict:
        p = {"status": status, "limit": str(limit)}
        if market_id: p["marketId"] = market_id
        if cursor: p["cursor"] = cursor
        return await self._req("GET", "/api/v5/predictions/positions", params=p)

    async def get_trade_history(self, market_id=None, cursor=None, limit=50) -> dict:
        p = {"limit": str(limit)}
        if market_id: p["marketId"] = market_id
        if cursor: p["cursor"] = cursor
        return await self._req("GET", "/api/v5/predictions/trades", params=p)

    async def heartbeat(self) -> dict:
        from collections import OrderedDict
        action = OrderedDict()
        action["type"] = "cancelAll"
        action["assetIds"] = []
        action["marketType"] = "prediction"
        return await self._signed_post("/api/v5/predictions/heartbeat", action)

    # ── Split / Merge ──
    async def split(self, market_id: str, size: str) -> dict:
        from collections import OrderedDict
        action = OrderedDict()
        action["type"] = "predictionSplit"
        action["marketId"] = market_id
        action["size"] = size
        return await self._signed_post("/api/v5/predictions/positions/split", action)

    async def merge(self, market_id: str, size: str) -> dict:
        from collections import OrderedDict
        action = OrderedDict()
        action["type"] = "predictionMerge"
        action["marketId"] = market_id
        action["size"] = size
        return await self._signed_post("/api/v5/predictions/positions/merge", action)

    async def redeem(self, market_id: str) -> dict:
        from collections import OrderedDict
        action = OrderedDict()
        action["type"] = "predictionRedeem"
        action["marketId"] = market_id
        return await self._signed_post("/api/v5/predictions/positions/redeem", action)

    async def close(self):
        await self.ws_disconnect()
        if self._http:
            await self._http.aclose()
            self._http = None


# singleton
_client: Optional[OkxClient] = None
def get_client() -> OkxClient:
    global _client
    if _client is None:
        _client = OkxClient()
    return _client
