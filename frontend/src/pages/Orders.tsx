import React, { useEffect, useState } from 'react'
import { Table, Button, Form, Input, Select, Space, message } from 'antd'
import { apiGet, apiPost } from '../api'

export default function OrdersPage() {
  const [loading, setLoading] = useState(false)
  const [orders, setOrders] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const r = await apiGet('/api/orders')
      setOrders((r.data && r.data.list) || [])
    } catch (e: any) {
      message.error(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const onFinish = async (vals: any) => {
    try {
      const r = await apiPost('/api/orders', vals)
      message.success('下单请求已发送')
      await load()
    } catch (e: any) {
      message.error(e.message || '下单失败')
    }
  }

  const cancel = async (record: any) => {
    try {
      await apiPost('/api/orders/cancel', { asset_id: record.assetId || record.asset_id, order_id: record.oid || record.orderId })
      message.success('撤单请求已发送')
      await load()
    } catch (e: any) {
      message.error(e.message || '撤单失败')
    }
  }

  return (
    <div>
      <h2>订单管理</h2>
      <Form form={form} layout="inline" onFinish={onFinish} style={{ marginBottom: 16 }}>
        <Form.Item name="asset_id" rules={[{ required: true }]}> 
          <Input placeholder="asset_id" />
        </Form.Item>
        <Form.Item name="side" initialValue="BUY">
          <Select style={{ width: 100 }}>
            <Select.Option value="BUY">BUY</Select.Option>
            <Select.Option value="SELL">SELL</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="price" rules={[{ required: true }]}> 
          <Input placeholder="price" />
        </Form.Item>
        <Form.Item name="size" rules={[{ required: true }]}> 
          <Input placeholder="size" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit">下单</Button>
        </Form.Item>
        <Form.Item>
          <Button onClick={load}>刷新订单</Button>
        </Form.Item>
      </Form>

      <Table rowKey={(r) => r.oid || r.orderId} loading={loading} dataSource={orders}>
        <Table.Column title="OrderId" dataIndex="oid" />
        <Table.Column title="Asset" dataIndex="assetId" />
        <Table.Column title="Side" dataIndex="side" />
        <Table.Column title="Price" dataIndex="price" />
        <Table.Column title="Size" dataIndex="size" />
        <Table.Column title="Status" dataIndex="status" />
        <Table.Column title="Action" key="action" render={(text, record: any) => (
          <Space>
            <Button size="small" onClick={() => cancel(record)}>Cancel</Button>
          </Space>
        )} />
      </Table>
    </div>
  )
}
