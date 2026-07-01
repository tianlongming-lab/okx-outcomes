import React from 'react'
import { Layout, Menu } from 'antd'
import { Link, Routes, Route, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import EventsPage from './pages/Events'
import OrdersPage from './pages/Orders'
import BotPage from './pages/Bot'
import './styles.css'

const { Header, Sider, Content } = Layout

export default function App() {
  const location = useLocation()
  const selected = location.pathname.split('/')[1] || 'dashboard'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="light">
        <div style={{ padding: 16, fontWeight: 700 }}>OKX Outcomes</div>
        <Menu mode="inline" selectedKeys={[selected]}>
          <Menu.Item key="dashboard"><Link to="/">仪表盘</Link></Menu.Item>
          <Menu.Item key="events"><Link to="/events">事件/市场</Link></Menu.Item>
          <Menu.Item key="orders"><Link to="/orders">订单管理</Link></Menu.Item>
          <Menu.Item key="bot"><Link to="/bot">做市机器人</Link></Menu.Item>
        </Menu>
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 16px' }}>
          <div style={{ float: 'right', color: '#666' }}>本地开发</div>
        </Header>
        <Content style={{ margin: 16 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/events" element={<EventsPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/bot" element={<BotPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
