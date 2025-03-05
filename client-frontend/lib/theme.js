
import { createTheme } from '@mui/material/styles';
import { blue, green, grey, red, orange } from '@mui/material/colors';

// Define color palette variables
const primaryMain = '#2563eb';  // Blue color for primary actions
const secondaryMain = '#10b981'; // Green for success and highlights
const errorMain = '#ef4444';    // Red for errors
const warningMain = '#f97316';  // Orange for warnings
const infoMain = '#3b82f6';     // Blue for information
const backgroundDefault = '#f9fafb'; // Light grey background
const backgroundPaper = '#ffffff';   // White for paper/card backgrounds

// Typography configuration
const fontFamily = 'var(--font-inter), "Roboto", "Helvetica", "Arial", sans-serif';

// Create theme with extensive customizations
const theme = createTheme({
  palette: {
    primary: {
      main: primaryMain,
      light: blue[300],
      dark: blue[700],
      contrastText: '#fff',
    },
    secondary: {
      main: secondaryMain,
      light: green[300],
      dark: green[700],
      contrastText: '#fff',
    },
    error: {
      main: errorMain,
      light: red[300],
      dark: red[700],
      contrastText: '#fff',
    },
    warning: {
      main: warningMain,
      light: orange[300],
      dark: orange[700],
      contrastText: '#fff',
    },
    info: {
      main: infoMain,
      light: blue[200],
      dark: blue[800],
      contrastText: '#fff',
    },
    text: {
      primary: grey[900],
      secondary: grey[700],
      disabled: grey[500],
    },
    background: {
      default: backgroundDefault,
      paper: backgroundPaper,
    },
    divider: grey[200],
    action: {
      active: grey[600],
      hover: grey[100],
      selected: grey[200],
      disabled: grey[300],
      disabledBackground: grey[200],
    },
  },
  typography: {
    fontFamily,
    h1: {
      fontSize: '2.5rem',
      fontWeight: 600,
      lineHeight: 1.2,
      marginBottom: '0.5em',
    },
    h2: {
      fontSize: '2rem',
      fontWeight: 600,
      lineHeight: 1.3,
      marginBottom: '0.5em',
    },
    h3: {
      fontSize: '1.75rem',
      fontWeight: 600,
      lineHeight: 1.3,
    },
    h4: {
      fontSize: '1.5rem',
      fontWeight: 500,
      lineHeight: 1.4,
    },
    h5: {
      fontSize: '1.25rem',
      fontWeight: 500,
      lineHeight: 1.4,
    },
    h6: {
      fontSize: '1.1rem',
      fontWeight: 500,
      lineHeight: 1.5,
    },
    subtitle1: {
      fontSize: '1rem',
      lineHeight: 1.5,
      fontWeight: 500,
    },
    subtitle2: {
      fontSize: '0.9rem',
      lineHeight: 1.5,
      fontWeight: 500,
    },
    body1: {
      fontSize: '1rem',
      lineHeight: 1.6,
    },
    body2: {
      fontSize: '0.9rem',
      lineHeight: 1.6,
    },
    button: {
      fontWeight: 500,
      textTransform: 'none',
    },
    caption: {
      fontSize: '0.8rem',
      lineHeight: 1.5,
    },
    overline: {
      fontSize: '0.75rem',
      fontWeight: 500,
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
    },
  },
  shape: {
    borderRadius: 8,
  },
  spacing: (factor) => `${0.5 * factor}rem`, // 1 = 0.5rem = 8px
  components: {
    // Card customization for job listings
    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.08)',
          transition: 'transform 0.2s, box-shadow 0.2s',
          '&:hover': {
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.12)',
            transform: 'translateY(-4px)',
          },
        },
      },
    },
    // Button customizations
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
          borderRadius: 8,
          padding: '8px 16px',
        },
        containedPrimary: {
          boxShadow: '0 2px 4px rgba(37, 99, 235, 0.2)',
          '&:hover': {
            boxShadow: '0 4px 8px rgba(37, 99, 235, 0.3)',
          },
        },
        outlinedPrimary: {
          borderWidth: '1.5px',
        },
      },
    },
    // Chip customization for skills tags
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 500,
        },
        outlined: {
          borderWidth: '1.5px',
        },
      },
    },
    // TextField customization
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: 8,
          },
        },
      },
    },
    // List items for job listings
    MuiListItem: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    // Paper component
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
        elevation1: {
          boxShadow: '0 1px 4px rgba(0, 0, 0, 0.08)',
        },
      },
    },
    // Tab components for filtering
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
        },
      },
    },
  },
  // Custom breakpoints for responsive design
  breakpoints: {
    values: {
      xs: 0,
      sm: 600,
      md: 900,
      lg: 1200,
      xl: 1536,
    },
  },
});

export default theme;