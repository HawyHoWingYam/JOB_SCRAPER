
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
  },
  {
    id: 4,
    title: 'Backend Developer',
    company: 'Cloud Services Corp',
    location: 'Seattle, WA',
    description: 'Seeking a skilled Backend Developer to design and implement robust APIs and server-side logic.',
    salary: '$105,000 - $140,000',
    postedDate: '3 days ago',
    skills: ['Java', 'Spring Boot', 'REST APIs', 'Docker']
  },
  {
    id: 5,
    title: 'Mobile App Developer',
    company: 'Innovate Mobile',
    location: 'Los Angeles, CA',
    description: 'Develop innovative mobile applications for iOS and Android platforms using React Native.',
    salary: '$95,000 - $125,000',
    postedDate: '5 days ago',
    skills: ['React Native', 'iOS', 'Android', 'Redux']
  },
  {
    id: 6,
    title: 'DevOps Engineer',
    company: 'Automation Experts',
    location: 'Austin, TX',
    description: 'Implement and manage our CI/CD pipelines and infrastructure as code to ensure smooth deployments.',
    salary: '$115,000 - $155,000',
    postedDate: '2 weeks ago',
    skills: ['AWS', 'Terraform', 'Jenkins', 'Kubernetes']
  },
  {
    id: 7,
    title: 'UX Designer',
    company: 'UserFirst Design',
    location: 'Chicago, IL',
    description: 'Create intuitive and engaging user experiences for our web and mobile applications.',
    salary: '$85,000 - $115,000',
    postedDate: '1 day ago',
    skills: ['Figma', 'Sketch', 'User Research', 'Wireframing']
  },
  {
    id: 8,
    title: 'AI Research Scientist',
    company: 'AI Frontier Labs',
    location: 'Mountain View, CA',
    description: 'Conduct cutting-edge research in artificial intelligence and machine learning to develop new algorithms.',
    salary: '$130,000 - $170,000',
    postedDate: 'Today',
    skills: ['Python', 'TensorFlow', 'PyTorch', 'Deep Learning']
  },
  {
    id: 9,
    title: 'Security Engineer',
    company: 'CyberGuard Solutions',
    location: 'Washington, D.C.',
    description: 'Protect our systems and data from cyber threats by implementing security measures and conducting vulnerability assessments.',
    salary: '$120,000 - $160,000',
    postedDate: '4 days ago',
    skills: ['Cybersecurity', 'Penetration Testing', 'SIEM', 'Firewalls']
  },
  {
    id: 10,
    title: 'Product Manager',
    company: 'Global Tech Products',
    location: 'London, UK (Remote)',
    description: 'Lead the development and launch of new software products from conception to market.',
    salary: '$95,000 - $135,000',
    postedDate: '1 week ago',
    skills: ['Product Management', 'Agile', 'Market Research', 'Roadmapping']
  },
  {
    id: 11,
    title: 'Data Engineer',
    company: 'DataStream Analytics',
    location: 'Denver, CO',
    description: 'Build and maintain data pipelines to support our data science and analytics initiatives.',
    salary: '$110,000 - $145,000',
    postedDate: '6 days ago',
    skills: ['Spark', 'Hadoop', 'ETL', 'Cloud Data Warehousing']
  },
  {
    id: 12,
    title: 'Technical Writer',
    company: 'Clarity Communications',
    location: 'Remote',
    description: 'Create clear and concise documentation for our software products and APIs.',
    salary: '$75,000 - $100,000',
    postedDate: '2 days ago',
    skills: ['Technical Writing', 'API Documentation', 'Markdown', 'Confluence']
  },
  {
    id: 13,
    title: 'QA Engineer',
    company: 'Quality Assurance Group',
    location: 'San Jose, CA',
    description: 'Ensure the quality of our software products through manual and automated testing.',
    salary: '$80,000 - $110,000',
    postedDate: 'Today',
    skills: ['Selenium', 'Test Automation', 'Jira', 'Agile']
  },
  {
    id: 14,
    title: 'Cloud Architect',
    company: 'Nimbus Solutions',
    location: 'New York, NY',
    description: 'Design and implement scalable and secure cloud infrastructure solutions for our clients.',
    salary: '$135,000 - $175,000',
    postedDate: '3 days ago',
    skills: ['AWS', 'Azure', 'GCP', 'Terraform']
  },
  {
    id: 15,
    title: 'Machine Learning Engineer',
    company: 'AlgoTech Dynamics',
    location: 'San Francisco, CA (Hybrid)',
    description: 'Develop and deploy machine learning models to solve complex business problems.',
    salary: '$125,000 - $165,000',
    postedDate: '1 week ago',
    skills: ['Python', 'TensorFlow', 'Scikit-learn', 'Data Science']
  },
  {
    id: 16,
    title: 'Blockchain Developer',
    company: 'Decentralized Innovations',
    location: 'Remote',
    description: 'Build decentralized applications and smart contracts using blockchain technologies.',
    salary: '$110,000 - $150,000',
    postedDate: '5 days ago',
    skills: ['Solidity', 'Ethereum', 'Web3.js', 'Cryptography']
  },
  {
    id: 17,
    title: 'Game Developer',
    company: 'Pixel Perfect Games',
    location: 'Los Angeles, CA',
    description: 'Create engaging and immersive gaming experiences for various platforms.',
    salary: '$85,000 - $120,000',
    postedDate: '2 days ago',
    skills: ['Unity', 'C#', 'Game Design', '3D Modeling']
  },
  {
    id: 18,
    title: 'Network Engineer',
    company: 'Connect Global',
    location: 'Dallas, TX',
    description: 'Design, implement, and maintain our network infrastructure to ensure reliable connectivity.',
    salary: '$90,000 - $130,000',
    postedDate: 'Today',
    skills: ['Cisco', 'Routing', 'Switching', 'Network Security']
  },
  {
    id: 19,
    title: 'Business Intelligence Analyst',
    company: 'Insight Analytics Group',
    location: 'Chicago, IL',
    description: 'Analyze business data and create dashboards to provide insights and support decision-making.',
    salary: '$80,000 - $115,000',
    postedDate: '4 days ago',
    skills: ['SQL', 'Tableau', 'Power BI', 'Data Analysis']
  },
  {
    id: 20,
    title: 'Technical Support Engineer',
    company: 'HelpDesk Solutions',
    location: 'Atlanta, GA',
    description: 'Provide technical support to customers and resolve their software and hardware issues.',
    salary: '$65,000 - $90,000',
    postedDate: '1 week ago',
    skills: ['Troubleshooting', 'Customer Service', 'Windows', 'Linux']
  },
  {
    id: 21,
    title: 'UI Developer',
    company: 'Visual Interface Design',
    location: 'Boston, MA',
    description: 'Develop user interfaces for web applications using modern front-end technologies.',
    salary: '$85,000 - $120,000',
    postedDate: '6 days ago',
    skills: ['HTML', 'CSS', 'JavaScript', 'React']
  },
  {
    id: 22,
    title: 'Data Visualization Specialist',
    company: 'Visualize Insights',
    location: 'Seattle, WA (Remote)',
    description: 'Create compelling data visualizations to communicate insights and trends to stakeholders.',
    salary: '$90,000 - $125,000',
    postedDate: '2 weeks ago',
    skills: ['Tableau', 'D3.js', 'Data Storytelling', 'Infographics']
  },
  {
    id: 23,
    title: 'Embedded Systems Engineer',
    company: 'Edge Computing Solutions',
    location: 'San Diego, CA',
    description: 'Design and develop embedded software for IoT devices and edge computing platforms.',
    salary: '$100,000 - $140,000',
    postedDate: 'Yesterday',
    skills: ['C', 'C++', 'Embedded Linux', 'IoT']
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