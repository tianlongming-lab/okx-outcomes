import React, { useEffect, useState } from 'react'
import { Card, Button, InputNumber, Form, Switch, message } from 'antd'
import { apiGet, apiPost } from '../api'

export default function BotPage() {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    try {
      const r = await apiGet('/api/bot/stats')
      setStats(r)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => { load() }, [])

  const start = async () => {
    setLoading(true)
    try {
      const vals = form.getFieldsValue()
      await apiPost('/api/bot/start', vals)
      message.success('正在启动机器人')
      await load()
    } catch (e: any) {
      message.error(e.message || '启动失败')
    } finally { setLoading(false) }
  }

  const stop = async () => {
    setLoading(true)
    try {
      await apiPost('/api/bot/stop')
      message.success('已停止机器人')
      await load()
    } catch (e: any) {
      message.error(e.message || '停止失败')
    } finally { setLoading(false) }
  }

  const saveConfig = async () => {
    const vals = form.getFieldsValue()
    try {
      await apiPost('/api/bot/config', vals)
      message.success('配置已保存')
      await load()
    } catch (e: any) {
      message.error(e.message || '保存失败')
    }
  }

  return (
    <div>
      <h2>做市机器人</h2>
      <Card style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" initialValues={{ spread_tick: 0.01, order_size: 10 }}>
          <Form.Item name="yes_asset_id" label="asset_id"><input /></Form.Item>
          <Form.Item name="spread_tick" label="spread">
            <InputNumber step={0.001} />
          </Form.Item>
          <Form.Item name="order_size" label="size">
            <InputNumber />
          </Form.Item>
          <Form.Item name="protection_enabled" label="保护">
            <Switch />
          </Form.Item>
          <Form.Item>
            <Button type="primary" onClick={saveConfig}>保存配置</Button>
          </Form.Item>
        </Form>

        <div style={{ marginTop: 12 }}>
          <Button type="primary" onClick={start} disabled={loading}>启动</Button>
          <Button style={{ marginLeft: 8 }} onClick={stop} disabled={loading}>停止</Button>
        </div>
      </Card>

      <Card title="机器人状态">
        <div>状态: {stats?.status}</div>
        <div>已成交: {stats?.trades_count}</div>
        <div>利润(合计): {stats?.profit_total}</div>
        <div>活跃买单: {stats?.active_buy_orders} / 卖单: {stats?.active_sell_orders}</div>
      </Card>
    </div>
  )
}
