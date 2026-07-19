import React, { useState } from 'react';

function SkillTags({ skills, onSkillClick, maxDisplay = 5 }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const normalizedSkills = Array.isArray(skills) ? skills : [];

  if (normalizedSkills.length === 0) {
    return null;
  }

  const colors = ['--primary', '--accent', '--success'];
  const shouldCollapse = normalizedSkills.length > maxDisplay;
  const displaySkills = shouldCollapse && !isExpanded
    ? normalizedSkills.slice(0, maxDisplay)
    : normalizedSkills;
  const skillCounts = new Map();
  const keyedSkills = displaySkills.map((skill) => {
    const occurrence = skillCounts.get(skill) ?? 0;
    skillCounts.set(skill, occurrence + 1);

    return {
      key: occurrence === 0 ? skill : `${skill}-${occurrence}`,
      skill,
    };
  });

  return (
    <div className="skill-tags-container">
      {keyedSkills.map(({ key, skill }, index) => (
        <span
          key={key}
          className="skill-tag"
          style={{
            background: `var(${colors[index % colors.length]})`,
            cursor: onSkillClick ? 'pointer' : 'default',
          }}
          onClick={() => onSkillClick?.(skill)}
        >
          {skill}
        </span>
      ))}
      {shouldCollapse && (
        <button
          type="button"
          className="skill-tag-more"
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded((currentValue) => !currentValue)}
        >
          {isExpanded ? 'Show less' : `+${normalizedSkills.length - maxDisplay} more`}
        </button>
      )}
    </div>
  );
}

export default SkillTags;
