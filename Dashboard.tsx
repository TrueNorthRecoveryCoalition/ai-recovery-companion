import React, { useState, useEffect } from 'react';
import {
  Container,
  Grid,
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
  LinearProgress,
} from '@mui/material';
import {
  Assignment as TaskIcon,
  TrendingUp as TrendingUpIcon,
  People as PeopleIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  Schedule as ScheduleIcon,
} from '@mui/icons-material';
import { useSocket } from '../contexts/SocketContext';
import { useNotification } from '../contexts/NotificationContext';

// Types
interface DashboardStats {
  active_tasks: number;
  completed_today: number;
  active_users: number;
  crisis_alerts: number;
  avg_response_time: number;
  wellness_trend: string;
}

interface RecentActivity {
  id: string;
  type: string;
  user_alias: string;
  message: string;
  timestamp: string;
  priority: 'low' | 'medium' | 'high' | 'critical';
}

const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<DashboardStats>({n    active_tasks: 0,
    completed_today: 0,
    active_users: 0,
    crisis_alerts: 0,
    avg_response_time: 0,
    wellness_trend: 'stable',
  });
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);
  const [loading, setLoading] = useState(true);
  
  const { isConnected } = useSocket();
  const { showNotification } = useNotification();

  useEffect(() => {
    fetchDashboardData();
    
    // Set up real-time updates
    const handleRefresh = () => {
      fetchDashboardData();
    };
    
    window.addEventListener('refresh_tasks', handleRefresh);
    
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchDashboardData, 30000);
    
    return () => {
      window.removeEventListener('refresh_tasks', handleRefresh);
      clearInterval(interval);
    };
  }, []);

  const fetchDashboardData = async () => {
    try {
      const [statsResponse, activityResponse] = await Promise.all([
        fetch('/api/v1/dashboard/stats'),
        fetch('/api/v1/dashboard/recent-activity'),
      ]);

      if (statsResponse.ok && activityResponse.ok) {
        const statsData = await statsResponse.json();
        const activityData = await activityResponse.json();
        
        setStats(statsData);
        setRecentActivity(activityData.activities || []);
      }
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
      showNotification('Failed to load dashboard data', 'error');
    } finally {
      setLoading(false);
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
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

  const getWellnessTrendIcon = (trend: string) => {
    switch (trend) {
      case 'improving':
        return <TrendingUpIcon color="success" />;
      case 'declining':
        return <WarningIcon color="warning" />;
      default:
        return <CheckCircleIcon color="info" />;
    }
  };

  if (loading) {
    return (
      <Container maxWidth="lg">
        <Box sx={{ mt: 4 }}>
          <LinearProgress />
          <Typography sx={{ mt: 2 }}>Loading dashboard...</Typography>
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Mentor Dashboard
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Real-time status:
          </Typography>
          <Chip
            label={isConnected ? 'Connected' : 'Disconnected'}
            color={isConnected ? 'success' : 'error'}
            size="small"
          />
        </Box>
      </Box>

      {/* Stats Grid */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        {/* Active Tasks */}
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Avatar sx={{ bgcolor: 'primary.main', mr: 2 }}>
                  <TaskIcon />
                </Avatar>
                <Box>
                  <Typography variant="h6">{stats.active_tasks}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Active Tasks
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Completed Today */}
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Avatar sx={{ bgcolor: 'success.main', mr: 2 }}>
                  <CheckCircleIcon />
                </Avatar>
                <Box>
                  <Typography variant="h6">{stats.completed_today}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Completed Today
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Active Users */}
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Avatar sx={{ bgcolor: 'info.main', mr: 2 }}>
                  <PeopleIcon />
                </Avatar>
                <Box>
                  <Typography variant="h6">{stats.active_users}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Active Users
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Crisis Alerts */}
        <Grid item xs={12} sm={6} md={3}>
          <Card className={stats.crisis_alerts > 0 ? 'crisis-alert' : ''}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                <Avatar sx={{ bgcolor: 'error.main', mr: 2 }}>
                  <WarningIcon />
                </Avatar>
                <Box>
                  <Typography variant="h6">{stats.crisis_alerts}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Crisis Alerts
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        {/* Recent Activity */}
        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Recent Activity
              </Typography>
              
              {recentActivity.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  No recent activity
                </Typography>
              ) : (
                <List>
                  {recentActivity.slice(0, 10).map((activity, index) => (
                    <React.Fragment key={activity.id}>
                      <ListItem alignItems="flex-start">
                        <ListItemAvatar>
                          <Avatar
                            sx={{
                              bgcolor: `${getPriorityColor(activity.priority)}.main`,
                              width: 32,
                              height: 32,
                            }}
                          >
                            <TaskIcon fontSize="small" />
                          </Avatar>
                        </ListItemAvatar>
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography variant="body1">
                                {activity.user_alias}
                              </Typography>
                              <Chip
                                label={activity.priority}
                                size="small"
                                color={getPriorityColor(activity.priority) as any}
                                variant="outlined"
                              />
                            </Box>
                          }
                          secondary={
                            <>
                              <Typography variant="body2" color="text.primary">
                                {activity.message}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {new Date(activity.timestamp).toLocaleString()}
                              </Typography>
                            </>
                          }
                        />
                      </ListItem>
                      {index < recentActivity.length - 1 && <Divider />}
                    </React.Fragment>
                  ))}
                </List>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* System Status & Quick Actions */}
        <Grid item xs={12} md={4}>
          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                System Status
              </Typography>
              
              <Box sx={{ mb: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  {getWellnessTrendIcon(stats.wellness_trend)}
                  <Typography variant="body2">
                    Wellness Trend: {stats.wellness_trend}
                  </Typography>
                </Box>
                
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <ScheduleIcon color="info" />
                  <Typography variant="body2">
                    Avg Response: {stats.avg_response_time}s
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Quick Actions
              </Typography>
              
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Button
                  variant="contained"
                  fullWidth
                  href="/queue"
                  startIcon={<TaskIcon />}
                >
                  View Task Queue
                </Button>
                
                <Button
                  variant="outlined"
                  fullWidth
                  href="/analytics"
                  startIcon={<TrendingUpIcon />}
                >
                  View Analytics
                </Button>
                
                <Button
                  variant="outlined"
                  fullWidth
                  color="error"
                  onClick={() => {
                    // Trigger emergency protocol
                    showNotification('Emergency protocol activated', 'warning');
                  }}
                  startIcon={<WarningIcon />}
                >
                  Emergency Protocol
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Container>
  );
};

export default Dashboard;
