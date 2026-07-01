import React, { useEffect, useState } from 'react'
import { List, Card, Spin, Button } from 'antd'
import { apiGet } from '../api'

export default function EventsPage() {
  const [loading, setLoading] = useState(true)
  const [events, setEvents] = useState<any[]>([])

  useEffect(() => {
    (async () => {
      try {
        const r = await apiGet('/api/events')
        setEvents(r.data || [])
      } catch (e) {
        console.error(e)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  if (loading) return <Spin />

  return (
    <div>
      <h2>事件 / 市场</h2>
      <List
        grid={{ gutter: 16, column: 2 }}
        dataSource={events}
        renderItem={(item: any) => (
          <List.Item>
            <Card title={item.title || item.name || item.id}>
              <div>id: {item.id || item.eventId}</div>
              <div>状态: {item.status}</div>
              <div>成交量: {item.volume_24h}</div>
              <div style={{ marginTop: 8 }}>
                <Button size="small" onClick={() => window.open(`/api/events/${item.id || item.eventId}`, '_blank')}>查看</Button>
              </div>
            </Card>
          </List.Item>
        )}
      />
    </div>
  )
}
