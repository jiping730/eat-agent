import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AppProvider, useApp } from './AppContext';
import { AppShell } from '../components/AppShell';
import { ToastHost } from '../components/Toast';
import { LoadingState, ErrorState } from '../components/State';
import { AuthPage } from '../features/auth/AuthPage';
import { HomePage } from '../features/nutrition/HomePage';
import { ChatPage } from '../features/chat/ChatPage';
import { MealRecordsPage } from '../features/meal-records/MealRecordsPage';
import { NutritionPage } from '../features/nutrition/NutritionPage';
import { ProfilePage } from '../features/profile/ProfilePage';
import { KnowledgePage } from '../features/knowledge/KnowledgePage';
import { RecipesPage } from '../features/recipes/RecipesPage';

function Protected({ children }: { children: ReactNode }) {
  const { user, authLoading, authError, refreshUser } = useApp();
  if (authLoading) return <main className="flex min-h-screen items-center justify-center"><LoadingState label="正在校验登录状态" /></main>;
  if (authError) return <main className="mx-auto flex min-h-screen max-w-lg items-center px-4"><ErrorState message={authError} onRetry={() => void refreshUser()} /></main>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
function AppRoutes() {
  return <Routes><Route path="/login" element={<AuthPage />} /><Route element={<Protected><AppShell /></Protected>}><Route index element={<HomePage />} /><Route path="chat/:conversationId?" element={<ChatPage />} /><Route path="records" element={<MealRecordsPage />} /><Route path="nutrition" element={<NutritionPage />} /><Route path="recipes" element={<RecipesPage />} /><Route path="profile" element={<ProfilePage />} /><Route path="knowledge" element={<KnowledgePage />} /></Route><Route path="*" element={<Navigate to="/" replace />} /></Routes>;
}
export default function App() {
  return <BrowserRouter><AppProvider><AppRoutes /><ToastHost /></AppProvider></BrowserRouter>;
}
