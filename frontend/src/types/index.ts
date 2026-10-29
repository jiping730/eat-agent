export type ID = string;
export type MessageKind = 'advice' | 'calorie' | 'meal_plan' | 'clarification';
export type Message = {
  id: ID;
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
  kind?: MessageKind;
  feedback?: 'up' | 'down' | null;
  streaming?: boolean;
};
export type Conversation = {
  id: ID;
  title: string;
  updated_at?: string;
  archived?: boolean;
  messages?: Message[];
};
export type GrillOption = { label: string; value: string; description?: string };
export type GrillQuestion = {
  id: ID;
  field: string;
  question: string;
  reason: string;
  options: GrillOption[];
  allow_custom?: boolean;
};
export type GrillState = {
  status: 'waiting' | 'ready';
  question?: GrillQuestion;
  collected: Record<string, string>;
  missing?: string[];
};
export type User = { id: ID; username?: string; email?: string; nickname?: string; roles?: string[] };
export type Profile = {
  nickname: string;
  age?: number;
  gender?: string;
  height_cm?: number;
  weight_kg?: number;
  goal?: string;
  activity_level?: string;
  dietary_preferences: string[];
  restrictions: string[];
  allergies: string[];
  health_goal?: string;
  memory_enabled: boolean;
  personalization_enabled: boolean;
};
export type ProfileSuggestion = { id: ID; field: keyof Profile; label: string; value: string; reason: string };
export type KnowledgeDocument = {
  id: ID;
  title: string;
  content?: string;
  status: 'indexing' | 'ready' | 'failed';
  created_at?: string;
};
export type ExperienceSettings = { memory_enabled: boolean; personalization_enabled: boolean };
export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack';
export type MealRecord = {
  id: ID;
  date: string;
  meal_type: MealType;
  food_name: string;
  calories?: number;
  protein_g?: number;
  carbs_g?: number;
  fat_g?: number;
  note?: string;
  source: 'manual' | 'chat';
};
export type MealPlan = {
  id: ID;
  title: string;
  meal_type: MealType;
  reason: string;
  calories?: number;
  protein_g?: number;
  carbs_g?: number;
  fat_g?: number;
  content: string;
  created_at: string;
};
export type ApiTokens = { access_token: string; refresh_token?: string };
