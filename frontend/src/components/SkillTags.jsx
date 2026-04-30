import React from 'react';

function SkillTags({ skills, onSkillClick, maxDisplay = 5 }) {
  if (!skills || skills.length === 0) {
    return null;
  }

  const colors = ['--primary', '--accent', '--success'];
  const displaySkills = skills.slice(0, maxDisplay);
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
      {skills.length > maxDisplay && (
        <span className="skill-tag-more">+{skills.length - maxDisplay} more</span>
      )}
    </div>
  );
}

export default SkillTags;
