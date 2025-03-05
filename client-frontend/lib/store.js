import { configureStore } from '@reduxjs/toolkit';

export const store = configureStore({
  reducer: {
    // We'll add reducers here as we build features
    // jobs: jobsReducer,
  },
});