# 1. Create project directory
mkdir frontend
cd frontend

# 2. Initialize npm project
npm init -y

# 3. Install Vite and React dependencies
npm install vite @vitejs/plugin-react --save-dev
npm install react react-dom

# 4. Create project structure
mkdir -p src/components src/pages src/assets src/store

# 5. Create essential files
touch src/main.jsx src/App.jsx index.html vite.config.js

# 6. Set up Vite configuration
echo "import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true
  }
});" > vite.config.js


