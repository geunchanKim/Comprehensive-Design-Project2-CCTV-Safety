import { Link } from 'react-router'

// 시안은 있지만 아직 코드로 옮기지 않은 화면
export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="page">
      <header className="topbar">
        <h1 className="grow">{title}</h1>
      </header>
      <p className="page-message">
        아직 코드로 옮기지 않은 화면입니다. 지금은 <Link to="/areas/A">구역 관제 (A 작업장 1)</Link>만 동작합니다.
      </p>
    </div>
  )
}
