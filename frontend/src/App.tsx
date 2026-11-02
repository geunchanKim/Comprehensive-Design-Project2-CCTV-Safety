import { BrowserRouter, Route, Routes } from 'react-router'
import AppShell from './components/AppShell'
import AreaPage from './pages/AreaPage'
import PlaceholderPage from './pages/PlaceholderPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<PlaceholderPage title="전체 현황" />} />
          <Route path="areas/:areaId" element={<AreaPage />} />
          <Route path="events" element={<PlaceholderPage title="이벤트 기록" />} />
          <Route path="settings" element={<PlaceholderPage title="사업장·구역 설정" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
