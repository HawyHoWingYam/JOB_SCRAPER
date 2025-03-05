
// page.js need to 
// - Replace the local state management with Redux actions for search and filtering
// - Connect to API endpoints to fetch real job data
// - Implement advanced filtering options as outlined in your project instructions
// - Add pagination for handling larger sets of job listings
'use client';

import { useState } from 'react';
import { 
  Typography, 
  Container, 
  Box, 
  Button, 
  TextField, 
  Card, 
  CardContent,
  Grid,
  Chip,
  Divider
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import WorkIcon from '@mui/icons-material/Work';

// Mock data for initial development
const mockJobs = [
  {
    id: 1,
    title: 'Frontend Developer',
    company: 'Tech Innovations Inc.',
    location: 'New York, NY (Remote)',
    description: 'We are looking for an experienced Frontend Developer proficient in React and Next.js to join our growing team.',
    salary: '$90,000 - $120,000',
    postedDate: '2 days ago',
    skills: ['React', 'Next.js', 'TypeScript', 'Material-UI']
  },
  {
    id: 2,
    title: 'Full Stack Engineer',
    company: 'Digital Solutions Ltd.',
    location: 'San Francisco, CA',
    description: 'Join our team to build scalable web applications using modern JavaScript frameworks and backend technologies.',
    salary: '$110,000 - $150,000',
    postedDate: '1 week ago',
    skills: ['JavaScript', 'Node.js', 'PostgreSQL', 'AWS']
  },
  {
    id: 3,
    title: 'Data Scientist',
    company: 'Analytics Pro',
    location: 'Boston, MA (Hybrid)',
    description: 'Seeking a data scientist to analyze large datasets and build predictive models to drive business decisions.',
    salary: '$100,000 - $130,000',
    postedDate: 'Today',
    skills: ['Python', 'Machine Learning', 'SQL', 'Data Visualization']
  }
];

export default function HomePage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [filteredJobs, setFilteredJobs] = useState(mockJobs);

  // Simple search function to filter jobs
  const handleSearch = () => {
    if (!searchQuery.trim()) {
      setFilteredJobs(mockJobs);
      return;
    }
    
    const query = searchQuery.toLowerCase();
    const filtered = mockJobs.filter(job => 
      job.title.toLowerCase().includes(query) || 
      job.company.toLowerCase().includes(query) ||
      job.description.toLowerCase().includes(query) ||
      job.skills.some(skill => skill.toLowerCase().includes(query))
    );
    
    setFilteredJobs(filtered);
  };

  return (
    <Container maxWidth="lg">
      {/* Header Section */}
      <Box sx={{ my: 4, textAlign: 'center' }}>
        <Typography 
          variant="h2" 
          component="h1" 
          gutterBottom
          sx={{ 
            fontWeight: 'bold',
            background: 'linear-gradient(45deg, #556cd6 30%, #19857b 90%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent'
          }}
        >
          Job Scraper
        </Typography>
        <Typography variant="h5" color="text.secondary" paragraph>
          Find and analyze job opportunities efficiently
        </Typography>
      </Box>

      {/* Search Section */}
      <Box 
        sx={{ 
          display: 'flex', 
          flexDirection: { xs: 'column', sm: 'row' },
          gap: 2,
          mb: 4 
        }}
      >
        <TextField
          fullWidth
          variant="outlined"
          placeholder="Search for jobs, skills, or companies"
          InputProps={{
            startAdornment: <SearchIcon color="action" sx={{ mr: 1 }} />,
          }}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          sx={{ flex: 1 }}
        />
        <Button 
          variant="contained" 
          color="primary" 
          size="large"
          onClick={handleSearch}
          sx={{ 
            minWidth: { xs: '100%', sm: '120px' }
          }}
        >
          Search
        </Button>
      </Box>
      
      {/* Job Listings Section */}
      <Typography variant="h6" gutterBottom sx={{ mt: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          <WorkIcon sx={{ mr: 1 }} />
          Recent Job Listings ({filteredJobs.length})
        </Box>
      </Typography>
      <Divider sx={{ mb: 3 }} />
      
      <Grid container spacing={3}>
        {filteredJobs.map(job => (
          <Grid item xs={12} key={job.id}>
            <Card 
              elevation={2}
              sx={{ 
                transition: '0.3s',
                '&:hover': {
                  transform: 'translateY(-5px)',
                  boxShadow: 6,
                }
              }}
            >
              <CardContent>
                <Typography variant="h5" component="h2" gutterBottom>
                  {job.title}
                </Typography>
                <Typography variant="subtitle1" color="text.secondary" gutterBottom>
                  {job.company} • {job.location}
                </Typography>
                <Typography variant="body1" paragraph>
                  {job.description}
                </Typography>
                
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                  <Typography variant="subtitle2">
                    Salary: <strong>{job.salary}</strong>
                  </Typography>
                  <Typography variant="subtitle2" color="text.secondary">
                    Posted: {job.postedDate}
                  </Typography>
                </Box>
                
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                  {job.skills.map(skill => (
                    <Chip 
                      key={skill} 
                      label={skill} 
                      size="small"
                      color="primary"
                      variant="outlined"
                    />
                  ))}
                </Box>
                
                <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end' }}>
                  <Button variant="contained" size="small">
                    View Details
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      
      {filteredJobs.length === 0 && (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <Typography variant="h6" color="text.secondary">
            No jobs found matching your search criteria.
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Try adjusting your search terms or filters.
          </Typography>
        </Box>
      )}
      
      {/* Footer Section */}
      <Box sx={{ my: 4, textAlign: 'center' }}>
        <Divider sx={{ mb: 3 }} />
        <Typography variant="body2" color="text.secondary">
          © {new Date().getFullYear()} Job Scraper - Find your next opportunity
        </Typography>
      </Box>
    </Container>
  );
}