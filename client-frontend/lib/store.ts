import { configureStore } from '@reduxjs/toolkit';
import { useDispatch, useSelector, TypedUseSelectorHook } from 'react-redux';
import jobsReducer from './store/slices/jobsSlice';
import filtersReducer from './store/slices/filtersSlice';
import uiReducer from './store/slices/uiSlice';

// Define environment check that doesn't rely on process.env
const isDevelopment = () => {
  // Check if we're in a browser and not in production
  if (typeof window === 'undefined') return false;
  
  // Check if we're on localhost or a development domain
  const hostname = window.location.hostname;
  return hostname === 'localhost' || 
         hostname === '127.0.0.1' || 
         hostname.includes('dev.') || 
         hostname.includes('.local');
};

export const store = configureStore({
  reducer: {
    jobs: jobsReducer,
    filters: filtersReducer,
    ui: uiReducer,
  },
  middleware: (getDefaultMiddleware) => 
    getDefaultMiddleware({
      serializableCheck: {
        ignoredActions: ['persist/PERSIST'],
      },
    }),
  devTools: isDevelopment(),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;