# ARC Mentor Console

React-based dashboard for human mentors in the AI Recovery Companion platform.

## Features

- Real-time task queue management
- User conversation interface
- Crisis escalation handling
- Analytics and reporting
- User profile management

## Getting Started

### Prerequisites

- Node.js 16+
- npm or yarn
- ARC API server running

### Installation

```bash
cd mentor-console
npm install
```

### Environment Setup

Create `.env` file:

```bash
REACT_APP_API_BASE_URL=http://localhost:8000/api/v1
REACT_APP_WS_URL=ws://localhost:8000
REACT_APP_ENVIRONMENT=development
```

### Development

```bash
npm start
```

Opens [http://localhost:3000](http://localhost:3000)

### Build for Production

```bash
npm run build
```

## Architecture

- **React 18** with TypeScript
- **Material-UI** for components
- **Socket.IO** for real-time updates
- **Axios** for API calls
- **React Router** for navigation

## Key Components

- `TaskQueue` - Active mentor tasks
- `ConversationView` - Chat interface
- `UserProfile` - User context and history
- `Analytics` - Performance metrics
- `CrisisAlert` - Emergency notifications

## Development Notes

- Real-time updates via WebSocket
- Responsive design for mobile mentors
- Keyboard shortcuts for efficiency
- Automatic logout for security
