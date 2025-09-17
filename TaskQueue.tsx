import React, { useState, useEffect } from 'react';
import {
  Container,
  Card,
  CardContent,
  Typography,
  Box,
  Chip,
  Button,
  List,
  ListItem,
  ListItemText,
  ListItemAvatar,
  Avatar,
  Divider,
  Grid,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  LinearProgress,
  Alert,
} from '@mui/material';
import {
  Assignment as TaskIcon,
  Person as PersonIcon,
  Phone as PhoneIcon,
  Chat as ChatIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  Schedule as ScheduleIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { useSocket } from '../contexts/SocketContext';
import { useNotification } from '../contexts/NotificationContext';
import { useNavigate } from 'react-router-dom';

// Types
interface Task {
  id: string;
  task_sid: string;
  user_alias: string;
  user_id: string;
  session_type: 'chat' | 'voice' | 'emergency';
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  priority: number;
  created_at: string;
  context: {
    message?: string;
    risk_score?: number;
    escalation_reason?: string;
  };
  estimated_wait_time?: number;
}

const TaskQueue: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [acceptDialogOpen, setAcceptDialogOpen] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [notes, setNotes] = useState('');
  
  const { emit, isConnected } = useSocket();
  const { showNotification } = useNotification();
  const navigate = useNavigate();

  useEffect(() => {
    fetchTasks();
    
    // Set up real-time updates
    const handleRefresh = () => {
      fetchTasks();
    };
    
    window.addEventListener('refresh_tasks', handleRefresh);
    
    return () => {
      window.removeEventListener('refresh_tasks', handleRefresh);
    };
  }, []);

  const fetchTasks = async () => {
    try {
      const response = await fetch('/api/v1/escalations/active');
      if (response.ok) {
        const data = await response.json();
        setTasks(data.active_sessions || []);
      } else {
        showNotification('Failed to load tasks', 'error');
      }
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
      showNotification('Failed to load tasks', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleAcceptTask = (task: Task) => {
    setSelectedTask(task);
    setAcceptDialogOpen(true);
  };

  const confirmAcceptTask = async () => {
    if (!selectedTask) return;
    
    try {
      // Accept the task via socket
      emit('accept_task', {
        task_sid: selectedTask.task_sid,
        notes: notes,
      });
      
      showNotification(
        `Accepted ${selectedTask.risk_level} priority task for ${selectedTask.user_alias}`,
        'success'
      );
      
      // Navigate to conversation
      if (selectedTask.session_type === 'chat' || selectedTask.session_type === 'emergency') {
        navigate(`/conversation/${selectedTask.id}`);
      } else {
        // For voice calls, show call interface
        showNotification('Incoming voice call - please answer your phone', 'info');
      }
      
      setAcceptDialogOpen(false);
      setNotes('');
      setSelectedTask(null);
      
      // Refresh tasks
      fetchTasks();
      
    } catch (error) {
      console.error('Failed to accept task:', error);
      showNotification('Failed to accept task', 'error');
    }
  };

  const getPriorityColor = (risk_level: string) => {
    switch (risk_level) {
      case 'critical':
        return 'error';
      case 'high':
        return 'warning';
      case 'medium':
        return 'info';
      default:
        return 'success';
    }
  };

  const getTaskIcon = (session_type: string) => {
    switch (session_type) {
      case 'voice':
        return <PhoneIcon />;
      case 'emergency':
        return <WarningIcon />;
      default:
        return <ChatIcon />;
    }
  };

  const formatTimeAgo = (timestamp: string) => {
    const now = new Date();
    const time = new Date(timestamp);
    const diffMs = now.getTime() - time.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    
    return time.toLocaleDateString();
  };

  if (loading) {
    return (
      <Container maxWidth="lg">
        <Box sx={{ mt: 4 }}>
          <LinearProgress />
          <Typography sx={{ mt: 2 }}>Loading task queue...</Typography>
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      {/* Header */}
      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Task Queue
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              {tasks.length} active task{tasks.length !== 1 ? 's' : ''}
            </Typography>
            <Chip
              label={isConnected ? 'Connected' : 'Disconnected'}
              color={isConnected ? 'success' : 'error'}
              size="small"
            />
          </Box>
        </Box>
        
        <IconButton onClick={fetchTasks} disabled={loading}>
          <RefreshIcon />
        </IconButton>
      </Box>

      {/* Connection Status Alert */}
      {!isConnected && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          You are disconnected from the real-time system. Tasks may not update automatically.
        </Alert>
      )}

      {/* Task List */}
      {tasks.length === 0 ? (
        <Card>
          <CardContent sx={{ textAlign: 'center', py: 8 }}>
            <CheckCircleIcon sx={{ fontSize: 64, color: 'success.main', mb: 2 }} />
            <Typography variant="h6" gutterBottom>
              No Active Tasks
            </Typography>
            <Typography variant="body2" color="text.secondary">
              All current support requests have been handled. Great work!
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Grid container spacing={3}>
          {tasks.map((task) => (
            <Grid item xs={12} key={task.id}>
              <Card
                className={`${task.risk_level}-priority`}
                sx={{
                  ...(task.risk_level === 'critical' && {
                    border: 2,
                    borderColor: 'error.main',
                    boxShadow: '0 0 20px rgba(244, 67, 54, 0.3)',
                  }),
                }}
              >
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <Box sx={{ flex: 1 }}>
                      {/* Task Header */}
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                        <Avatar sx={{ bgcolor: `${getPriorityColor(task.risk_level)}.main` }}>
                          {getTaskIcon(task.session_type)}
                        </Avatar>
                        
                        <Box>
                          <Typography variant="h6">
                            {task.user_alias}
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                            <Chip
                              label={task.risk_level.toUpperCase()}
                              color={getPriorityColor(task.risk_level) as any}
                              size="small"
                            />
                            <Chip
                              label={task.session_type.toUpperCase()}
                              variant="outlined"
                              size="small"
                            />
                            <Typography variant="caption" color="text.secondary">
                              {formatTimeAgo(task.created_at)}
                            </Typography>
                          </Box>
                        </Box>
                      </Box>

                      {/* Task Context */}
                      {task.context.message && (
                        <Box sx={{ mb: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
                          <Typography variant="body2" color="text.secondary" gutterBottom>
                            Latest message:
                          </Typography>
                          <Typography variant="body1">
                            "{task.context.message}"
                          </Typography>
                        </Box>
                      )}

                      {/* Task Details */}
                      <Grid container spacing={2} sx={{ mb: 2 }}>
                        {task.context.risk_score && (
                          <Grid item xs={6} sm={3}>
                            <Typography variant="caption" color="text.secondary">
                              Risk Score
                            </Typography>
                            <Typography variant="body2" fontWeight="bold">
                              {(task.context.risk_score * 100).toFixed(0)}%
                            </Typography>
                          </Grid>
                        )}
                        
                        <Grid item xs={6} sm={3}>
                          <Typography variant="caption" color="text.secondary">
                            Priority
                          </Typography>
                          <Typography variant="body2" fontWeight="bold">
                            {task.priority}
                          </Typography>
                        </Grid>
                        
                        {task.estimated_wait_time && (
                          <Grid item xs={6} sm={3}>
                            <Typography variant="caption" color="text.secondary">
                              Est. Wait
                            </Typography>
                            <Typography variant="body2" fontWeight="bold">
                              {task.estimated_wait_time}m
                            </Typography>
                          </Grid>
                        )}
                      </Grid>
                    </Box>

                    {/* Action Buttons */}
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, ml: 2 }}>
                      <Button
                        variant="contained"
                        color={task.risk_level === 'critical' ? 'error' : 'primary'}
                        onClick={() => handleAcceptTask(task)}
                        startIcon={getTaskIcon(task.session_type)}
                        size="large"
                        sx={{
                          ...(task.risk_level === 'critical' && {
                            animation: 'pulse 2s infinite',
                          }),
                        }}
                      >
                        Accept
                      </Button>
                      
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={() => navigate(`/user/${task.user_id}`)}
                        startIcon={<PersonIcon />}
                      >
                        Profile
                      </Button>
                    </Box>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* Accept Task Dialog */}
      <Dialog open={acceptDialogOpen} onClose={() => setAcceptDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          Accept Task - {selectedTask?.user_alias}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            You are about to accept a {selectedTask?.risk_level} priority {selectedTask?.session_type} support session.
          </Typography>
          
          <TextField
            fullWidth
            multiline
            rows={3}
            label="Initial Notes (Optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Any initial observations or approach notes..."
            sx={{ mt: 2 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAcceptDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={confirmAcceptTask}
            variant="contained"
            color={selectedTask?.risk_level === 'critical' ? 'error' : 'primary'}
          >
            Accept Task
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default TaskQueue;
