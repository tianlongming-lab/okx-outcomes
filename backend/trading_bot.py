"""
OKX Prediction Market Maker Bot (Polymarket 适配)
策略：
  1. 在买1价格挂买单
  2. 买入成交后立即以 buy_price + spread_tick 挂卖单
  3. 如果行情恶化（best_bid 下跌），立即挂保护性卖单（防止亏损）
"""
import os, json, logging, asyncio, time, math
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("trading_bot")


@dataclass
class BotConfig:
    enabled: bool = False
    asset_id: str = ""
    yes_asset_id: str = ""
    no_asset_id: str = ""
    market_id: str = ""
    spread_tick: float = 0.01
    max_position_size: float = 100.0
    order_size: float = 10.0
    refresh_interval: int = 3
    max_active_orders: int = 4
    cancel_threshold_ms: int = 60000
    protection_enabled: bool = True
    protection_threshold: float = 0.02


@dataclass
class OwnOrder:
    order_id: str
    asset_id: str
    side: str  # BUY / SELL
    price: str
    size: str
    status: str = "ACTIVE"
    created_at: float = 0.0
    is_take_profit: bool = False
    is_protection: bool = False
    buy_price: Optional[float] = None


@dataclass
class BotStats:
    status: str = "stopped"
    trades_count: int = 0
    profit_total: float = 0.0
    last_trade_time: Optional[float] = None
    error_count: int = 0
    uptime: float = 0.0
    current_bid: float = 0.0
    current_ask: float = 0.0
    current_mid: float = 0.0
    active_buy_orders: int = 0
    active_sell_orders: int = 0
    protection_triggered: int = 0


class TradingBot:
    def __init__(self):
        self.config = BotConfig()
        self.stats = BotStats()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._start_time: Optional[float] = None
        self._own_orders: List[OwnOrder] = []
        self._last_orderbook: Optional[dict] = None
        self._last_best_bid: Optional[float] = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def update_config(self, config: dict):
        """更新机器人配置"""
        async with self._lock:
            was_running = self._running
            if was_running:
                await self._stop_inner()
            
            # 更新所有配置项
            for key, value in config.items():
                if hasattr(self.config, key):
                    if key == "spread_tick":
                        setattr(self.config, key, float(value))
                    elif key == "protection_threshold":
                        setattr(self.config, key, float(value))
                    elif key in ("order_size", "max_position_size"):
                        setattr(self.config, key, float(value))
                    elif key in ("max_active_orders", "refresh_interval", "cancel_threshold_ms"):
                        setattr(self.config, key, int(value))
                    elif key == "protection_enabled":
                        setattr(self.config, key, bool(value))
                    else:
                        setattr(self.config, key, value)
            
            if was_running:
                await self._start_inner()
            return {"status": "ok"}

    async def start(self, config: dict = None):
        """启动机器人"""
        async with self._lock:
            if self._running:
                return {"status": "already_running"}
            if config:
                await self.update_config(config)
            self.config.enabled = True
            return await self._start_inner()

    async def _start_inner(self):
        """内部启动逻辑"""
        if not self.config.yes_asset_id and not self.config.asset_id:
            return {"status": "error", "message": "缺少 asset_id / yes_asset_id"}
        
        self._running = True
        self._start_time = time.time()
        self.stats.status = "running"
        self._own_orders.clear()
        self._last_best_bid = None
        self._task = asyncio.create_task(self._run_loop())
        
        aid = self.config.yes_asset_id or self.config.asset_id
        logger.info("🚀 做市机器人启动 | asset=%s tick=%.3f size=%.2f protection=%s",
                   aid, self.config.spread_tick, self.config.order_size,
                   self.config.protection_enabled)
        return {"status": "started"}

    async def stop(self):
        """停止机器人"""
        async with self._lock:
            return await self._stop_inner()

    async def _stop_inner(self):
        """内部停止逻辑"""
        self._running = False
        self.config.enabled = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.stats.status = "stopped"
        if self._start_time:
            self.stats.uptime += time.time() - self._start_time
            self._start_time = None
        self._own_orders.clear()
        logger.info("⏹️  做市机器人已停止")
        return {"status": "stopped"}

    async def _run_loop(self):
        """主循环"""
        from .client import get_client
        client = get_client()
        aid = self.config.yes_asset_id or self.config.asset_id
        
        while self._running:
            try:
                # 获取订单簿
                ob = await client.get_orderbook(aid, sz=20)
                if ob.get("code") in (0, "0") and ob.get("data"):
                    self._last_orderbook = ob["data"][0]
                    await self._tick(client, aid)
                else:
                    logger.warning("⚠️ 订单簿获取失败: %s", ob.get("message", "unknown"))
                    self.stats.error_count += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("❌ 循环异常: %s", e)
                self.stats.error_count += 1
            
            await asyncio.sleep(self.config.refresh_interval)
            
            if self._start_time:
                self.stats.uptime = time.time() - self._start_time

    async def _tick(self, client, aid_param):
        """处理一次行情tick"""
        ob = self._last_orderbook
        if not ob:
            return
        
        asks = ob.get("asks", [])
        bids = ob.get("bids", [])
        
        best_ask = float(asks[0][0]) if asks else None
        best_bid = float(bids[0][0]) if bids else None
        mid = ((best_ask or 0) + (best_bid or 0)) / 2 if (best_ask and best_bid) else (best_bid or best_ask or 0)
        
        self.stats.current_bid = best_bid or 0
        self.stats.current_ask = best_ask or 0
        self.stats.current_mid = mid
        
        # 刷新订单状态
        await self._refresh_own_orders(client, aid_param)
        
        # 检查行情恶化
        if self.config.protection_enabled and best_bid:
            await self._check_market_deterioration(client, best_bid, aid_param)
        
        # 管理订单
        await self._manage_orders(client, best_bid, best_ask, mid, aid_param)
        
        self._last_best_bid = best_bid

    async def _check_market_deterioration(self, client, current_best_bid: float, aid: str):
        """检测行情恶化并触发保护性卖单"""
        if not self._last_best_bid:
            return
        
        bid_drop = self._last_best_bid - current_best_bid
        if bid_drop > self.config.protection_threshold:
            logger.warning("🚨 行情恶化: 买1从 %.3f 跌至 %.3f (下跌%.3f), 触发保护",
                          self._last_best_bid, current_best_bid, bid_drop)
            
            # 为未成交的买单挂保护性卖单
            active_buy = [o for o in self._own_orders 
                         if o.side == "BUY" and o.status == "ACTIVE" 
                         and o.asset_id == aid and not o.is_protection]
            
            for buy_order in active_buy:
                buy_price = float(buy_order.price)
                has_protection = any(
                    o.side == "SELL" and o.is_protection 
                    and abs(float(o.price) - buy_price) < 0.001
                    and o.status == "ACTIVE"
                    for o in self._own_orders
                )
                
                if not has_protection:
                    await self._place_protection_sell(client, buy_price, buy_order.size, aid)
                    self.stats.protection_triggered += 1

    async def _place_protection_sell(self, client, price: float, size: str, asset_id: str):
        """挂保护性卖单"""
        try:
            price_str = f"{price:.3f}"
            r = await client.place_order(asset_id=asset_id, side="SELL",
                                        price=price_str, size=size)
            if r.get("code") in (0, "0"):
                order_id = r.get("data", {}).get("txHash") or f"prot_{int(time.time()*1000)}"
                prot_order = OwnOrder(
                    order_id=order_id,
                    asset_id=asset_id, side="SELL", price=price_str,
                    size=size, status="ACTIVE", created_at=time.time(),
                    is_protection=True, buy_price=price
                )
                self._own_orders.append(prot_order)
                logger.info("🛡️ 保护卖单 SELL %s @ %s", size, price_str)
            else:
                logger.error("❌ 保护卖单失败: %s", r.get("message"))
        except Exception as e:
            logger.error("❌ 保护卖单异常: %s", e)

    async def _refresh_own_orders(self, client, aid):
        """刷新订单状态"""
        try:
            r = await client.list_orders(status="open", limit=50)
            if r.get("code") not in (0, "0") or not r.get("data", {}).get("list"):
                # 清除超时的本地订单
                self._own_orders = [o for o in self._own_orders if o.status != "ACTIVE"]
                return
            
            remote = r["data"]["list"]
            remote_map = {o["oid"]: o for o in remote}
            now_t = time.time()
            
            # 更新订单状态
            for o in list(self._own_orders):
                if o.order_id in remote_map:
                    ro = remote_map[o.order_id]
                    o.status = ro.get("status", o.status)
                    fs = ro.get("filledSize", "0")
                    
                    if ro.get("status") in ("FILLED", "PARTIALLY_FILLED", "CANCELLED", "EXPIRED", "FAILED"):
                        o.status = ro["status"]
                        if ro["status"] in ("FILLED", "PARTIALLY_FILLED") and float(fs or "0") > 0:
                            await self._on_order_filled(client, o, ro, float(fs or "0"))
                else:
                    # 本地订单超过2分钟未找到，移除
                    if now_t - o.created_at > 120:
                        self._own_orders.remove(o)
            
            # 统计活跃订单
            active = [ro for ro in remote if ro.get("status") == "ACTIVE"]
            self.stats.active_buy_orders = sum(1 for a in active if a.get("side") == "BUY")
            self.stats.active_sell_orders = sum(1 for a in active if a.get("side") == "SELL")
        except Exception as e:
            logger.error("❌ 刷新订单失败: %s", e)

    async def _on_order_filled(self, client, own: OwnOrder, remote: dict, filled_size: float):
        """订单成交回调"""
        filled_amount = float(remote.get("filledAmount", "0") or "0")
        
        if own.is_take_profit or own.is_protection:
            # 止盈或保护卖单成交
            self.stats.trades_count += 1
            self.stats.profit_total += filled_amount
            self.stats.last_trade_time = time.time()
            order_type = "止盈" if own.is_take_profit else "保护"
            logger.info("✅ %s成交 利润=%.4f", order_type, filled_amount)
            self._own_orders.remove(own)
            return
        
        # 买入单成交 → 挂卖单
        self.stats.trades_count += 1
        self.stats.last_trade_time = time.time()
        logger.info("✅ 买入成交 size=%.2f @ %s", filled_size, own.price)
        self._own_orders.remove(own)
        
        buy_price = float(own.price)
        sell_price = buy_price + self.config.spread_tick
        
        if sell_price >= 1.0:
            logger.warning("⚠️ 卖出价格>=1.0, 跳过止盈")
            return
        
        await self._place_sell(client, sell_price, str(filled_size), own.asset_id)

    async def _place_sell(self, client, price: float, size: str, asset_id: str):
        """挂止盈卖单"""
        try:
            price_str = f"{price:.3f}"
            r = await client.place_order(asset_id=asset_id, side="SELL",
                                        price=price_str, size=size)
            if r.get("code") in (0, "0"):
                order_id = r.get("data", {}).get("txHash") or f"tp_{int(time.time()*1000)}"
                tp_order = OwnOrder(
                    order_id=order_id,
                    asset_id=asset_id, side="SELL", price=price_str,
                    size=size, status="ACTIVE", created_at=time.time(),
                    is_take_profit=True
                )
                self._own_orders.append(tp_order)
                logger.info("📈 止盈挂单 SELL %s @ %s", size, price_str)
            else:
                logger.error("❌ 止盈挂单失败: %s", r.get("message"))
        except Exception as e:
            logger.error("❌ 止盈挂单异常: %s", e)

    async def _manage_orders(self, client, best_bid, best_ask, mid, aid):
        """管理买单"""
        try:
            r = await client.list_orders(status="open", limit=50)
            if r.get("code") not in (0, "0") or not r.get("data", {}).get("list"):
                return
            
            active = r["data"]["list"]
            active_buy = [o for o in active if o.get("side") == "BUY" 
                         and o.get("assetId") == aid and o.get("status") == "ACTIVE"]
            now_ms = int(time.time() * 1000)
            
            # 撤销过期或过时的买单
            for o in active_buy:
                oid = o.get("oid", "")
                price = float(o.get("price", "0"))
                created = int(o.get("createdAt", "0"))
                age = now_ms - created
                should_cancel = False
                
                if best_bid and price < best_bid - 0.005:
                    should_cancel = True
                    logger.info("📉 撤销落后买单 oid=%s price=%.3f bid=%.3f", 
                               oid[:8], price, best_bid)
                
                if age > self.config.cancel_threshold_ms:
                    should_cancel = True
                    logger.info("⏱️ 撤销过期买单 oid=%s 已挂%.1fs", oid[:8], age/1000)
                
                if should_cancel:
                    await client.cancel_order(asset_id=aid, order_id=oid)
                    await asyncio.sleep(0.3)
            
            # 补充新的买单
            buy_count = len(active_buy)
            need = max(0, self.config.max_active_orders - buy_count)
            if need > 0 and best_bid and best_bid > 0:
                for i in range(need):
                    px = best_bid - (i * 0.005)
                    if px < 0.001:
                        break
                    px_str = f"{px:.3f}"
                    sz_str = str(int(self.config.order_size))
                    logger.info("🟢 挂买单 %s @ %s", sz_str, px_str)
                    
                    r2 = await client.place_order(asset_id=aid, side="BUY",
                                                 price=px_str, size=sz_str)
                    if r2.get("code") in (0, "0"):
                        order_id = r2.get("data", {}).get("txHash") or f"buy_{int(time.time()*1000)}"
                        self._own_orders.append(OwnOrder(
                            order_id=order_id,
                            asset_id=aid, side="BUY", price=px_str,
                            size=sz_str, created_at=time.time()
                        ))
                        logger.info("✓ 买单已发送")
                    await asyncio.sleep(0.3)
        except Exception as e:
            logger.error("❌ 管理订单异常: %s", e)

    def get_stats(self) -> dict:
        """获取机器人统计信息"""
        return {
            "status": self.stats.status,
            "trades_count": self.stats.trades_count,
            "profit_total": round(self.stats.profit_total, 4),
            "last_trade_time": self.stats.last_trade_time,
            "error_count": self.stats.error_count,
            "uptime": round(self.stats.uptime, 1),
            "current_bid": self.stats.current_bid,
            "current_ask": self.stats.current_ask,
            "current_mid": self.stats.current_mid,
            "active_buy_orders": self.stats.active_buy_orders,
            "active_sell_orders": self.stats.active_sell_orders,
            "own_orders": len(self._own_orders),
            "protection_triggered": self.stats.protection_triggered,
            "config": {
                "asset_id": self.config.asset_id,
                "yes_asset_id": self.config.yes_asset_id,
                "no_asset_id": self.config.no_asset_id,
                "market_id": self.config.market_id,
                "spread_tick": self.config.spread_tick,
                "order_size": self.config.order_size,
                "max_position_size": self.config.max_position_size,
                "max_active_orders": self.config.max_active_orders,
                "refresh_interval": self.config.refresh_interval,
                "protection_enabled": self.config.protection_enabled,
                "protection_threshold": self.config.protection_threshold,
                "enabled": self.config.enabled,
            }
        }


_bot: Optional[TradingBot] = None
def get_bot() -> TradingBot:
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot
