# React Mosaic Migration Guide for Cocai

## Executive Summary

This document provides a comprehensive analysis of migrating Cocai's hand-written multi-pane UI to use `@nomcopter/react-mosaic`, a mature React component for creating tiling window managers.

## Current vs Proposed Architecture

### Current Implementation (Vanilla JS + Split.js)
- **Technology**: Pure JavaScript, HTML, CSS with Split.js for resizing
- **Layout**: Fixed 3-column structure with vertical splits
- **Bundle Size**: ~20KB (Split.js + custom code)
- **Development Model**: Manual DOM manipulation
- **Maintenance**: Direct element updates, manual state management

### Proposed Implementation (React + Mosaic)
- **Technology**: React + TypeScript with react-mosaic-component
- **Layout**: Flexible binary tree structure supporting unlimited nesting
- **Bundle Size**: ~200KB (React ecosystem + Mosaic)
- **Development Model**: Component-based with declarative state management
- **Maintenance**: React's virtual DOM, automated re-rendering

## Migration Requirements

### 1. Build System Setup

#### Required Dependencies
```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0", 
    "react-mosaic-component": "^6.1.1",
    "@blueprintjs/core": "^5.8.1",
    "@blueprintjs/icons": "^5.6.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.43",
    "@types/react-dom": "^18.2.17",
    "@vitejs/plugin-react": "^4.2.1",
    "typescript": "^5.2.2",
    "vite": "^5.0.8"
  }
}
```

#### Build Configuration (Vite)
```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'public/dist',
    emptyOutDir: true
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/chat': 'http://localhost:8000'
    }
  }
})
```

### 2. FastAPI Backend Changes

#### Serve React Build in Production
```python
# src/server.py changes
from fastapi.staticfiles import StaticFiles

# Replace current static file serving
if os.getenv('NODE_ENV') == 'production':
    # Serve React build
    app.mount("/static", StaticFiles(directory="public/dist/assets"), name="static")
    
    @app.get("/play", response_class=HTMLResponse)
    async def play_ui():
        """Serve React app."""
        with open("public/dist/index.html", encoding="utf-8") as f:
            return f.read()
else:
    # Development: proxy to Vite dev server or serve existing files
    app.mount("/public", StaticFiles(directory="public"), name="public")
    
    @app.get("/play", response_class=HTMLResponse) 
    async def play_ui():
        """Serve existing play.html in development."""
        with open("public/play.html", encoding="utf-8") as f:
            return f.read()
```

### 3. Component Architecture

#### Panel Type Definitions
```typescript
enum PanelType {
  HISTORY = 'history',
  CLUES = 'clues',
  ILLUSTRATION = 'illustration',
  CHAT = 'chat', 
  STATS = 'stats',
  SKILLS = 'skills'
}
```

#### Mosaic Layout Definition
```typescript
const INITIAL_LAYOUT: MosaicNode<PanelType> = {
  direction: 'row',
  first: {
    direction: 'column',
    first: PanelType.HISTORY,
    second: PanelType.CLUES,
    splitPercentage: 50
  },
  second: {
    direction: 'row', 
    first: {
      direction: 'column',
      first: PanelType.ILLUSTRATION,
      second: PanelType.CHAT,
      splitPercentage: 40
    },
    second: {
      direction: 'column',
      first: PanelType.STATS, 
      second: PanelType.SKILLS,
      splitPercentage: 45
    },
    splitPercentage: 75
  },
  splitPercentage: 22
};
```

### 4. SSE Integration

#### React Hook for Server-Sent Events
```typescript
export function useSSE() {
  const [gameData, setGameData] = useState<GameData>(initialGameData);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const eventSource = new EventSource('/api/events');
    
    eventSource.onopen = () => setConnected(true);
    eventSource.onclose = () => setConnected(false);
    
    eventSource.onmessage = (event) => {
      const message: SSEMessage = JSON.parse(event.data);
      
      switch (message.type) {
        case 'history':
          setGameData(prev => ({ ...prev, history: message.history }));
          break;
        case 'clues':
          setGameData(prev => ({ ...prev, clues: message.clues }));
          break;
        case 'illustration':
          setGameData(prev => ({ ...prev, illustration_url: message.url }));
          break;
        case 'pc':
          setGameData(prev => ({ ...prev, pc: message.pc }));
          break;
      }
    };

    return () => eventSource.close();
  }, []);

  return { gameData, connected };
}
```

## Implementation Phases

### Phase 1: Infrastructure Setup (2-3 days)
1. **Install build system**
   ```bash
   npm init -y
   npm install react react-dom react-mosaic-component @blueprintjs/core @blueprintjs/icons
   npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom
   ```

2. **Configure build tools**
   - Set up `vite.config.ts`
   - Configure `tsconfig.json`
   - Create development/production build scripts

3. **Update FastAPI routing**
   - Add production/development mode detection
   - Configure static file serving for React build
   - Maintain backward compatibility

### Phase 2: Component Development (3-4 days)
1. **Convert render functions to React components**
   - `HistoryPanel` component
   - `CluesPanel` with expandable items
   - `IllustrationPanel` for scene display
   - `ChatPanel` iframe wrapper
   - `StatsPanel` responsive grid
   - `SkillsPanel` with roll buttons

2. **Implement data hooks**
   - `useSSE` hook for real-time updates
   - Type-safe interfaces matching current data structures
   - Error handling and reconnection logic

### Phase 3: Layout Implementation (2-3 days)
1. **Mosaic integration**
   - Configure initial layout matching current 3-column design
   - Implement layout persistence to localStorage
   - Add panel title configuration

2. **Responsive handling**
   - Detect screen size breakpoints
   - Switch layouts for mobile/desktop
   - Handle panel visibility

### Phase 4: Feature Parity (2-3 days)
1. **Interactive features**
   - Skill roll button integration with chat
   - Clue accordion expansion
   - Layout reset functionality

2. **Accessibility**
   - Keyboard navigation
   - ARIA labels
   - Screen reader support

3. **Styling**
   - Match existing Cocai theme
   - Blueprint.js customization
   - Responsive design

### Phase 5: Testing & Migration (1-2 days)
1. **Testing**
   - Cross-browser compatibility
   - Layout persistence
   - SSE reconnection
   - Mobile responsiveness

2. **Migration**
   - Switch production routing to React app
   - Remove old HTML/JS files
   - Update documentation

## Benefits of Migration

### ✅ Enhanced Functionality
- **Advanced layouts**: Unlimited nesting, tabs, floating windows
- **Drag & drop**: Rearrange panels by dragging
- **Layout persistence**: Save custom layouts per user
- **Professional UI**: Blueprint.js components and theming

### ✅ Developer Experience
- **Type safety**: Full TypeScript support
- **Component model**: Reusable, testable components
- **Modern tooling**: Hot reload, dev tools, debugging
- **Maintainability**: Cleaner separation of concerns

### ✅ Future Extensibility
- **Multiple sessions**: Tab support for different games
- **Plugin architecture**: Easy to add new panels
- **Advanced features**: Window management, keyboard shortcuts
- **Team development**: Better collaboration with component boundaries

## Challenges & Mitigation

### ⚠️ Bundle Size Increase
- **Challenge**: ~10x increase in JavaScript bundle size
- **Mitigation**: 
  - Code splitting for panels
  - Tree shaking unused Blueprint components
  - Lazy loading for non-essential features
  - Consider Progressive Web App caching

### ⚠️ Development Complexity
- **Challenge**: Build system and React learning curve
- **Mitigation**:
  - Phased migration approach
  - Maintain existing system during transition
  - Comprehensive documentation and training

### ⚠️ SSE Integration Complexity
- **Challenge**: Managing React state with external events
- **Mitigation**:
  - Custom hooks for clean abstraction
  - Error boundaries for graceful failures
  - Proper cleanup to prevent memory leaks

## Alternative Approaches

### 1. Hybrid Migration (Recommended for gradual adoption)
- Keep existing Split.js layout system
- Migrate complex panels (Skills, Clues) to React using portals
- Lower risk, incremental benefits

### 2. Different Layout Libraries
- **react-grid-layout**: For dashboard-style layouts
- **golden-layout**: More features but larger bundle
- **flexlayout-react**: Better tab support

### 3. Enhanced Vanilla Approach
- Keep current system but add:
  - TypeScript for better maintainability
  - Modern build system for optimization
  - Component-like organization

## Cost-Benefit Analysis

| Aspect | Current System | React Mosaic | Impact |
|--------|---------------|--------------|--------|
| Development Time | Fast for simple changes | Slower initial setup | -2 weeks |
| Bundle Size | 20KB | 200KB | -180KB |
| Maintainability | Manual DOM updates | Component model | +High |
| Feature Richness | Basic resizing | Advanced layouts | +High |
| Developer Experience | Direct manipulation | Modern tooling | +High |
| Type Safety | None | Full TypeScript | +High |
| Testing | Manual browser testing | Component testing | +High |
| Extensibility | Limited | Plugin-friendly | +High |

## Recommendations

### ✅ **Proceed with full migration if:**
- Team has React experience or willingness to learn
- Long-term maintainability is a priority
- Advanced layout features are desired (tabs, floating windows)
- Type safety and modern development practices are valued

### 🔄 **Consider hybrid approach if:**
- Current system meets most needs
- Development resources are limited
- Want to gain React benefits incrementally
- Risk tolerance is low

### ❌ **Stay with current system if:**
- No advanced layout requirements
- Bundle size is critical constraint
- Team strongly prefers vanilla JavaScript
- Time constraints prevent migration

## Proof of Concept Results

The working proof of concept demonstrates:
- ✅ **Layout parity**: Successfully recreated 3-column layout
- ✅ **Data integration**: SSE hook working with mock data
- ✅ **Visual consistency**: Maintained Cocai's dark theme
- ✅ **Interactive features**: Skills with roll buttons, expandable clues
- ✅ **Type safety**: Full TypeScript implementation
- ✅ **Modern tooling**: Vite dev server with hot reload

## Final Recommendation

**Recommended approach: Hybrid migration** starting with converting the Skills and Clues panels to React components while maintaining the existing Split.js layout system. This provides:

1. **Lower risk** - Keep proven layout system
2. **Immediate benefits** - Better component organization for complex UI
3. **Learning opportunity** - Team gains React experience gradually
4. **Future flexibility** - Can evolve to full Mosaic later

The full React Mosaic migration should be considered for a future major version when advanced layout features become necessary or when the team is fully comfortable with React development.