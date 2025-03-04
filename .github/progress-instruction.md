HawyHoWingYam: @workspace Expand the job listings page with more detailed filtering options

Workspace: Collecting workspace information# Expanding Job Listings Page with Detailed Filtering Options

## Problem Restatement

You need to enhance your job scraper application by adding more sophisticated filtering capabilities to the job listings page. Currently, you have a basic search functionality that filters jobs by keyword, but you need a comprehensive filtering system that allows users to narrow down job listings based on multiple criteria such as location, job type, salary range, date posted, and required skills.

## Current State Analysis

Your application already has:
1. A basic search bar that filters jobs based on text matching in title, company, and description
2. A Redux store with a `filtersSlice` that contains state for various filter criteria
3. A simple job listing display using Material-UI cards

However, the UI only exposes the search query filter, while the Redux store is already prepared for additional filtering options.

## Analogous Examples

1. **LinkedIn Job Search**: Provides filters for location, job type, experience level, and more in a sidebar panel with options to expand/collapse categories.

2. **Indeed Job Search**: Uses a combination of dropdown filters and a collapsible advanced filter panel that appears below the search bar.

3. **Glassdoor**: Implements filter chips that appear as tags after selection, allowing users to easily see and remove active filters.

## Anticipated Challenges

1. **UI Complexity**: Designing an interface that accommodates multiple filter types while remaining user-friendly on all devices
2. **Filter Logic**: Implementing efficient filtering algorithms that can handle combinations of different filter types
3. **Performance**: Ensuring the UI remains responsive when applying multiple filters to large datasets
4. **State Management**: Keeping track of applied filters and enabling easy modification

## Solution Exploration

### Solution 1: Expandable Sidebar Filter Panel

**Description**: Create a collapsible sidebar that contains categorized filter options. Users can expand/collapse filter sections as needed.

**Pros**:
- Clean organization of multiple filter categories
- Maximizes vertical space for displaying filter options
- Familiar pattern used by many job sites

**Cons**:
- Takes horizontal space away from job listings on smaller screens
- Requires careful responsive design to avoid UI issues on mobile

**Cost Estimate**: 3-4 days for implementation and thorough testing

### Solution 2: Filter Accordion Above Job Listings

**Description**: Add an expandable accordion panel above the job listings that contains all filter options organized by category.

**Pros**:
- Doesn't take horizontal space from job listings
- Easy to collapse when not in use
- Good for mobile-first design

**Cons**:
- Pushes job listings down when expanded
- Limited space for displaying many filter options at once

**Cost Estimate**: 2-3 days for implementation and testing

### Solution 3: Persistent Filter Bar with Filter Dialog

**Description**: Maintain a compact filter bar with summary chips, with an option to open a full-screen dialog for detailed filter configuration.

**Pros**:
- Compact UI that doesn't overwhelm the user
- Full screen dialog provides ample space for detailed configuration
- Works well across all device sizes

**Cons**:
- Requires more interaction steps to configure detailed filters
- Additional UI complexity with multiple views

**Cost Estimate**: 3-4 days for implementation and testing

## Recommended Solution

I recommend **Solution 3: Persistent Filter Bar with Filter Dialog** for the following reasons:

1. It provides the best balance between UI simplicity and filtering power
2. It works well across all device sizes without major UI compromises
3. The filter chips provide clear visibility of active filters
4. The approach is scalable as more filter options are added

## Implementation Plan

### Step 1: Create Filter Components

1. Create a FilterBar component for displaying active filters as chips
2. Create a FilterDialog component for configuring detailed filter options
3. Create individual filter components for each filter type:
   - LocationFilter (autocomplete text input)
   - JobTypeFilter (checkbox group)
   - SalaryRangeFilter (slider)
   - DatePostedFilter (radio button group)
   - SkillsFilter (chip input with suggestions)
   - SortBySelector (dropdown)

### Step 2: Enhance Redux Logic

1. Update the fetchJobs thunk to consider all filter parameters
2. Add actions and reducers for each filter type
3. Implement filter persistence using localStorage

### Step 3: UI Integration

1. Add the FilterBar component to the main job listings page
2. Implement the FilterDialog with all filter components
3. Add open/close dialog functionality
4. Style components for consistency with the application theme

Here's the implementation:

```javascript
// lib/store/slices/jobsSlice.js - Enhanced fetchJobs thunk

export const fetchJobs = createAsyncThunk(
  'jobs/fetchJobs',
  async (_, { getState }) => {
    const { filters } = getState();
    const { 
      searchQuery, 
      location, 
      jobType, 
      salary, 
      datePosted, 
      skills,
      sortBy 
    } = filters;
    
    // Apply all filters to the mock data
    let filteredJobs = [...mockJobData];
    
    // Filter by search query
    if (searchQuery && searchQuery.trim() !== '') {
      const lowercaseQuery = searchQuery.toLowerCase();
      filteredJobs = filteredJobs.filter(job => 
        job.title.toLowerCase().includes(lowercaseQuery) ||
        job.company.toLowerCase().includes(lowercaseQuery) ||
        job.description.toLowerCase().includes(lowercaseQuery)
      );
    }
    
    // Filter by location
    if (location && location.trim() !== '') {
      const lowercaseLocation = location.toLowerCase();
      filteredJobs = filteredJobs.filter(job => 
        job.location.toLowerCase().includes(lowercaseLocation)
      );
    }
    
    // Filter by job type
    if (jobType && jobType !== 'all') {
      filteredJobs = filteredJobs.filter(job => job.jobType === jobType);
    }
    
    // Filter by salary range
    if (salary && (salary.min > 0 || salary.max < 200000)) {
      filteredJobs = filteredJobs.filter(job => {
        // Extract numeric salary values from string like "$90,000 - $120,000"
        const salaryText = job.salary;
        const salaryNumbers = salaryText.match(/\d+,\d+/g);
        if (!salaryNumbers || salaryNumbers.length < 2) return false;
        
        const minSalary = parseInt(salaryNumbers[0].replace(',', ''));
        const maxSalary = parseInt(salaryNumbers[1].replace(',', ''));
        
        return (minSalary >= salary.min && maxSalary <= salary.max);
      });
    }
    
    // Filter by date posted
    if (datePosted && datePosted !== 'anytime') {
      const now = new Date();
      const cutoffDate = new Date();
      
      switch(datePosted) {
        case 'today':
          cutoffDate.setDate(now.getDate() - 1);
          break;
        case 'week':
          cutoffDate.setDate(now.getDate() - 7);
          break;
        case 'month':
          cutoffDate.setMonth(now.getMonth() - 1);
          break;
        default:
          break;
      }
      
      filteredJobs = filteredJobs.filter(job => {
        const jobDate = new Date(job.datePosted);
        return jobDate >= cutoffDate;
      });
    }
    
    // Filter by skills
    if (skills && skills.length > 0) {
      filteredJobs = filteredJobs.filter(job => {
        return skills.every(skill => 
          job.skills.some(jobSkill => 
            jobSkill.toLowerCase() === skill.toLowerCase()
          )
        );
      });
    }
    
    // Sort results
    switch(sortBy) {
      case 'date':
        filteredJobs.sort((a, b) => new Date(b.datePosted) - new Date(a.datePosted));
        break;
      case 'salary':
        filteredJobs.sort((a, b) => {
          const aSalaryMatch = a.salary.match(/\d+,\d+/g);
          const bSalaryMatch = b.salary.match(/\d+,\d+/g);
          if (!aSalaryMatch || !bSalaryMatch) return 0;
          
          const aMaxSalary = parseInt(aSalaryMatch[1].replace(',', ''));
          const bMaxSalary = parseInt(bSalaryMatch[1].replace(',', ''));
          return bMaxSalary - aMaxSalary;
        });
        break;
      case 'relevance':
      default:
        // Default sorting (already sorted by relevance)
        break;
    }
    
    return filteredJobs;
  }
);
```

Now let's create the UI components:

```javascript
// components/ui/FilterBar.js
import React from 'react';
import { Box, Chip, Button } from '@mui/material';
import FilterListIcon from '@mui/icons-material/FilterList';
import { useSelector, useDispatch } from 'react-redux';
import { 
  updateLocation, 
  updateJobType, 
  updateSalary, 
  updateDatePosted, 
  removeSkill,
  resetFilters
} from '../../lib/store/slices/filtersSlice';
import { fetchJobs } from '../../lib/store/slices/jobsSlice';

export default function FilterBar({ onOpenFilterDialog }) {
  const dispatch = useDispatch();
  const filters = useSelector((state) => state.filters);
  const { location, jobType, salary, datePosted, skills } = filters;
  
  const hasActiveFilters = location || 
    jobType !== 'all' || 
    (salary.min > 0 || salary.max < 200000) || 
    datePosted !== 'anytime' || 
    skills.length > 0;
  
  const handleDelete = (filterType, value) => {
    switch (filterType) {
      case 'location':
        dispatch(updateLocation(''));
        break;
      case 'jobType':
        dispatch(updateJobType('all'));
        break;
      case 'salary':
        dispatch(updateSalary({ min: 0, max: 200000 }));
        break;
      case 'datePosted':
        dispatch(updateDatePosted('anytime'));
        break;
      case 'skill':
        dispatch(removeSkill(value));
        break;
      default:
        break;
    }
    dispatch(fetchJobs());
  };
  
  const handleResetFilters = () => {
    dispatch(resetFilters());
    dispatch(fetchJobs());
  };
  
  const renderSalaryLabel = () => {
    if (salary.min > 0 || salary.max < 200000) {
      return `$${salary.min.toLocaleString()} - $${salary.max.toLocaleString()}`;
    }
    return null;
  };
  
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2, alignItems: 'center' }}>
      <Button 
        variant="outlined" 
        startIcon={<FilterListIcon />}
        onClick={onOpenFilterDialog}
        sx={{ mr: 1 }}
      >
        Filters
      </Button>
      
      {location && (
        <Chip 
          label={`Location: ${location}`}
          onDelete={() => handleDelete('location')}
          color="primary"
          variant="outlined"
        />
      )}
      
      {jobType !== 'all' && (
        <Chip 
          label={`Type: ${jobType}`}
          onDelete={() => handleDelete('jobType')}
          color="primary"
          variant="outlined"
        />
      )}
      
      {renderSalaryLabel() && (
        <Chip 
          label={`Salary: ${renderSalaryLabel()}`}
          onDelete={() => handleDelete('salary')}
          color="primary"
          variant="outlined"
        />
      )}
      
      {datePosted !== 'anytime' && (
        <Chip 
          label={`Posted: ${datePosted}`}
          onDelete={() => handleDelete('datePosted')}
          color="primary"
          variant="outlined"
        />
      )}
      
      {skills.map((skill) => (
        <Chip 
          key={skill}
          label={skill}
          onDelete={() => handleDelete('skill', skill)}
          color="primary"
        />
      ))}
      
      {hasActiveFilters && (
        <Button 
          variant="text" 
          size="small" 
          onClick={handleResetFilters}
          sx={{ ml: 'auto' }}
        >
          Clear All
        </Button>
      )}
    </Box>
  );
}
```

```javascript
// components/ui/FilterDialog.js
import React, { useState } from 'react';
import { 
  Dialog, 
  DialogTitle, 
  DialogContent, 
  DialogActions, 
  Button,
  Typography,
  TextField,
  FormControl,
  FormLabel,
  RadioGroup,
  FormControlLabel,
  Radio,
  Slider,
  Box,
  Chip,
  InputLabel,
  Select,
  MenuItem,
  Autocomplete,
  Divider
} from '@mui/material';
import { useSelector, useDispatch } from 'react-redux';
import { 
  updateLocation,
  updateJobType,
  updateSalary,
  updateDatePosted,
  addSkill,
  removeSkill,
  updateSortBy,
  resetFilters
} from '../../lib/store/slices/filtersSlice';
import { fetchJobs } from '../../lib/store/slices/jobsSlice';

const jobTypes = ['all', 'full-time', 'part-time', 'contract', 'internship', 'remote'];
const dateOptions = ['anytime', 'today', 'week', 'month'];
const sortOptions = ['relevance', 'date', 'salary'];
const skillSuggestions = [
  'JavaScript', 'React', 'Angular', 'Vue', 'Node.js', 'Python',
  'Java', 'C#', '.NET', 'SQL', 'MongoDB', 'AWS', 'Docker',
  'Kubernetes', 'DevOps', 'Machine Learning', 'Data Analysis'
];

export default function FilterDialog({ open, onClose }) {
  const dispatch = useDispatch();
  const filters = useSelector((state) => state.filters);
  
  // Local state for form controls
  const [localFilters, setLocalFilters] = useState(filters);
  const [skillInput, setSkillInput] = useState('');
  
  React.useEffect(() => {
    setLocalFilters(filters);
  }, [filters, open]);
  
  const handleLocationChange = (event) => {
    setLocalFilters({ ...localFilters, location: event.target.value });
  };
  
  const handleJobTypeChange = (event) => {
    setLocalFilters({ ...localFilters, jobType: event.target.value });
  };
  
  const handleSalaryChange = (event, newValue) => {
    setLocalFilters({ ...localFilters, salary: { min: newValue[0], max: newValue[1] } });
  };
  
  const handleDatePostedChange = (event) => {
    setLocalFilters({ ...localFilters, datePosted: event.target.value });
  };
  
  const handleSortByChange = (event) => {
    setLocalFilters({ ...localFilters, sortBy: event.target.value });
  };
  
  const handleAddSkill = () => {
    if (skillInput && !localFilters.skills.includes(skillInput)) {
      setLocalFilters({
        ...localFilters,
        skills: [...localFilters.skills, skillInput]
      });
      setSkillInput('');
    }
  };
  
  const handleRemoveSkill = (skillToRemove) => {
    setLocalFilters({
      ...localFilters,
      skills: localFilters.skills.filter(skill => skill !== skillToRemove)
    });
  };
  
  const handleApplyFilters = () => {
    // Update Redux store with all filter values
    dispatch(updateLocation(localFilters.location));
    dispatch(updateJobType(localFilters.jobType));
    dispatch(updateSalary(localFilters.salary));
    dispatch(updateDatePosted(localFilters.datePosted));
    
    // Clear and re-add all skills
    localFilters.skills.forEach(skill => {
      dispatch(addSkill(skill));
    });
    
    dispatch(updateSortBy(localFilters.sortBy));
    
    // Fetch jobs with new filters
    dispatch(fetchJobs());
    
    onClose();
  };
  
  const handleResetFilters = () => {
    dispatch(resetFilters());
    setLocalFilters({
      searchQuery: '',
      location: '',
      jobType: 'all',
      salary: { min: 0, max: 200000 },
      datePosted: 'anytime',
      skills: [],
      sortBy: 'relevance',
    });
  };
  
  return (
    <Dialog 
      open={open} 
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      aria-labelledby="filter-dialog-title"
    >
      <DialogTitle id="filter-dialog-title">
        Filter Jobs
      </DialogTitle>
      <DialogContent dividers>
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>Location</Typography>
          <TextField
            fullWidth
            placeholder="City, state, or remote"
            variant="outlined"
            value={localFilters.location}
            onChange={handleLocationChange}
            size="small"
          />
        </Box>
        
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>Job Type</Typography>
          <FormControl component="fieldset">
            <RadioGroup 
              row
              value={localFilters.jobType}
              onChange={handleJobTypeChange}
            >
              {jobTypes.map(type => (
                <FormControlLabel 
                  key={type}
                  value={type} 
                  control={<Radio size="small" />} 
                  label={type.charAt(0).toUpperCase() + type.slice(1)} 
                />
              ))}
            </RadioGroup>
          </FormControl>
        </Box>
        
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>
            Salary Range: ${localFilters.salary.min.toLocaleString()} - ${localFilters.salary.max.toLocaleString()}
          </Typography>
          <Slider
            value={[localFilters.salary.min, localFilters.salary.max]}
            onChange={handleSalaryChange}
            valueLabelDisplay="auto"
            min={0}
            max={200000}
            step={5000}
          />
        </Box>
        
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>Date Posted</Typography>
          <FormControl component="fieldset">
            <RadioGroup 
              row
              value={localFilters.datePosted}
              onChange={handleDatePostedChange}
            >
              {dateOptions.map(option => (
                <FormControlLabel 
                  key={option}
                  value={option} 
                  control={<Radio size="small" />} 
                  label={option.charAt(0).toUpperCase() + option.slice(1)} 
                />
              ))}
            </RadioGroup>
          </FormControl>
        </Box>
        
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>Required Skills</Typography>
          <Autocomplete
            freeSolo
            options={skillSuggestions}
            inputValue={skillInput}
            onInputChange={(event, newValue) => setSkillInput(newValue)}
            renderInput={(params) => (
              <TextField
                {...params}
                variant="outlined"
                size="small"
                placeholder="Add a skill"
                sx={{ mb: 1 }}
              />
            )}
          />
          <Button 
            variant="outlined" 
            size="small" 
            onClick={handleAddSkill}
            disabled={!skillInput}
          >
            Add Skill
          </Button>
          
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 2 }}>
            {localFilters.skills.map((skill) => (
              <Chip
                key={skill}
                label={skill}
                onDelete={() => handleRemoveSkill(skill)}
                color="primary"
                size="small"
              />
            ))}
          </Box>
        </Box>
        
        <Divider sx={{ my: 2 }} />
        
        <Box>
          <Typography variant="subtitle1" gutterBottom>Sort By</Typography>
          <FormControl fullWidth size="small">
            <Select
              value={localFilters.sortBy}
              onChange={handleSortByChange}
            >
              {sortOptions.map(option => (
                <MenuItem key={option} value={option}>
                  {option.charAt(0).toUpperCase() + option.slice(1)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleResetFilters} color="inherit">
          Reset All
        </Button>
        <Button onClick={onClose} color="inherit">
          Cancel
        </Button>
        <Button onClick={handleApplyFilters} color="primary" variant="contained">
          Apply Filters
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

Finally, let's update the main page to incorporate these components:

```javascript
// app/page.js
'use client';

import { useState, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { 
  Typography, 
  Container, 
  Box, 
  Button, 
  TextField, 
  Grid, 
  Card, 
  CardContent,
  Divider,
  Chip 
} from '@mui/material';
import { fetchJobs } from '../lib/store/slices/jobsSlice';
import { updateSearchQuery } from '../lib/store/slices/filtersSlice';
import FilterBar from '../components/ui/FilterBar';
import FilterDialog from '../components/ui/FilterDialog';

export default function Home() {
  const dispatch = useDispatch();
  const { items: jobs, loading, error } = useSelector((state) => state.jobs);
  const { searchQuery } = useSelector((state) => state.filters);
  const [filterDialogOpen, setFilterDialogOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchJobs());
  }, [dispatch]);

  const handleSearchChange = (e) => {
    dispatch(updateSearchQuery(e.target.value));
  };

  const handleSearch = () => {
    dispatch(fetchJobs());
  };
  
  const handleOpenFilterDialog = () => {
    setFilterDialogOpen(true);
  };
  
  const handleCloseFilterDialog = () => {
    setFilterDialogOpen(false);
  };

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Typography variant="h2" component="h1" gutterBottom>
          Job Scraper
        </Typography>
        
        <Box sx={{ display: 'flex', mb: 2 }}>
          <TextField
            fullWidth
            label="Search Jobs"
            variant="outlined"
            value={searchQuery}
            onChange={handleSearchChange}
            sx={{ mr: 2 }}
          />
          <Button 
            variant="contained" 
            color="primary"
            onClick={handleSearch}
          >
            Search
          </Button>
        </Box>
        
        <FilterBar onOpenFilterDialog={handleOpenFilterDialog} />
        <FilterDialog 
          open={filterDialogOpen} 
          onClose={handleCloseFilterDialog} 
        />
        
        <Divider sx={{ my: 2 }} />
        
        {loading ? (
          <Typography>Loading jobs...</Typography>
        ) : error ? (
          <Typography color="error">Error: {error}</Typography>
        ) : (
          <>
            <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="subtitle1">
                {jobs.length} {jobs.length === 1 ? 'job' : 'jobs'} found
              </Typography>
            </Box>
            
            <Grid container spacing={3}>
              {jobs.map((job) => (
                <Grid item xs={12} key={job.id}>
                  <Card>
                    <CardContent>
                      <Typography variant="h5">{job.title}</Typography>
                      <Typography variant="subtitle1" color="text.secondary">
                        {job.company}
                      </Typography>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1 }}>
                        <Typography variant="body2">{job.location}</Typography>
                        <Typography variant="body2">{job.salary}</Typography>
                      </Box>
                      <Typography variant="body2" sx={{ mt: 1 }}>
                        {job.description}
                      </Typography>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 2 }}>
                        {job.skills.map((skill) => (
                          <Chip key={skill} label={skill} size="small" />
                        ))}
                      </Box>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2 }}>
                        <Typography variant="caption" color="text.secondary">
                          Posted: {job.datePosted}
                        </Typography>
                        <Button variant="outlined" size="small">
                          View Details
                        </Button>
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </>
        )}
      </Box>
    </Container>
  );
}
```

## Documentation

### Features

- **Search Functionality**: Text-based search across job titles, companies, and descriptions
- **Location Filtering**: Filter jobs by location (city, state or remote)
- **Job Type Filtering**: Filter by full-time, part-time, contract, internship, or remote positions
- **Salary Range Filtering**: Filter jobs by salary range using a slider
- **Date Posted Filtering**: Filter by how recently jobs were posted
- **Skills Filtering**: Include only jobs that require specific skills
- **Sorting Options**: Sort by relevance, date posted, or salary
- **Visual Filter Summary**: Active filters are displayed as chips for quick reference
- **Clear Filters**: Options to clear individual filters or all filters at once

### Usage Guide

1. **Basic Search**: Use the search bar at the top to search for keywords
2. **Apply Filters**: Click the "Filters" button to open the filter dialog
3. **Configure Filters**: Set your desired filters in the dialog
4. **Apply Changes**: Click "Apply Filters" to update the job listings
5. **View Active Filters**: Active filters are displayed as chips below the search bar
6. **Remove Filters**: Click the X on any filter chip to remove it, or use "Clear All"

### Future Maintenance

1. **Adding New Filter Types**:
   - Create a new filter state in the filtersSlice
   - Add corresponding UI components in FilterDialog
   - Enhance the filtering logic in the fetchJobs thunk

2. **API Integration**:
   - When connecting to a real backend API, update the fetchJobs thunk to use actual API calls
   - Consider implementing server-side filtering for better performance

3. **Performance Optimization**:
   - Add debounce to search input to reduce unnecessary API calls
   - Implement virtualized lists if job listings become very large
   - Consider pagination for improved performance with large datasets

This implementation provides a comprehensive filtering system for your job scraper application while maintaining a clean, intuitive UI that works well across device sizes.