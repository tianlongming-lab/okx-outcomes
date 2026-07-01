import React, { useEffect, useState } from 'react'
import { Card, Row, Col, Spin, Alert } from 'antd'
import { apiGet } from '../api'

export default function Dashboard() {
  const [loading, setLoading] = useState(true)
  const [health, setHealth] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    (async () => {
      try {
        const h = await apiGet('/api/health')
        setHealth(h)
      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  if (loading) return <Spin />
  if (error) return <Alert type="error" message={error} />

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={8}>
          <Card title="服务状态">
            <div>版本: {health.version}</div>
            <div>API 已配置: {String(health.api_configured)}</div>
            <div>可下单: {String(health.can_sign)}</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="说明">
            <div>前端已连接到后端。你可以在事件页查看市场与事件，在订单页下单或管理订单。</div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
