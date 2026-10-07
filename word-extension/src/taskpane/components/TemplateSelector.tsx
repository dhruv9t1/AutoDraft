import * as React from "react";
import { useState, useMemo } from "react";
import { Combobox, Option, Field, tokens, makeStyles } from "@fluentui/react-components";
import { ChevronDown20Regular, Dismiss16Regular } from "@fluentui/react-icons";
import { log } from "../../services/logger";

export interface Template {
  id: string;
  name: string;
}

export interface TemplateSelectorProps {
  templates: Template[];
  recentlyUsedTemplates?: Template[];
  onTemplateSelect: (template: Template | null) => void;
  onCreateNewTemplate?: (templateName: string) => void;
  allowCreate?: boolean; // If false, only allow selection, not creation
  label?: string; // Custom label for the field
}

const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    maxWidth: "100%",
    marginBottom: "24px",
  },
  comboboxField: {
    width: "100%",
    "& label": {
      fontSize: tokens.fontSizeBase400,
      fontWeight: tokens.fontWeightSemibold,
      color: tokens.colorNeutralForeground1,
      marginBottom: "8px",
    },
  },
  combobox: {
    fontSize: tokens.fontSizeBase300,
  },
  expandIconWrapper: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  clearIcon: {
    cursor: "pointer",
    color: tokens.colorNeutralForeground3,
    "&:hover": {
      color: tokens.colorNeutralForeground1,
    },
  },
});

const TemplateSelector: React.FC<TemplateSelectorProps> = (props: TemplateSelectorProps) => {
  const { templates, recentlyUsedTemplates = [], onTemplateSelect, onCreateNewTemplate, allowCreate = true, label = "Select or create a template" } = props;
  const [inputValue, setInputValue] = useState<string>("");
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [isSelecting, setIsSelecting] = useState<boolean>(false);
  const styles = useStyles();

  // Combine recently used templates (top 5) with all templates, removing duplicates
  const allTemplates = useMemo(() => {
    const recentIds = new Set(recentlyUsedTemplates.map((t) => t.id));
    const otherTemplates = templates.filter((t) => !recentIds.has(t.id));
    return [...recentlyUsedTemplates, ...otherTemplates];
  }, [templates, recentlyUsedTemplates]);

  // Filter templates based on search input
  const filteredTemplates = useMemo(() => {
    if (!inputValue.trim()) {
      return allTemplates;
    }
    const searchLower = inputValue.toLowerCase();
    return allTemplates.filter((template) =>
      template.name.toLowerCase().includes(searchLower)
    );
  }, [inputValue, allTemplates]);

  // Check if input value matches an existing template
  const isExistingTemplate = useMemo(() => {
    if (!inputValue.trim()) return false;
    return allTemplates.some(
      (template) => template.name.toLowerCase() === inputValue.toLowerCase()
    );
  }, [inputValue, allTemplates]);

  const handleOptionSelect = (_event: any, data: any) => {
    setIsSelecting(true);
    
    // Fluent UI v9 Combobox uses optionValue in the data object
    const selectedValue = data.optionValue || data.value;
    log("[TemplateSelector] Option selected");
    
    if (!selectedValue) {
      setIsSelecting(false);
      return;
    }
    
    // Check if user selected "Create new template" option
    if (selectedValue === "__CREATE_NEW__") {
      if (onCreateNewTemplate && inputValue.trim()) {
        const newTemplate: Template = {
          id: `new-${Date.now()}`,
          name: inputValue.trim(),
        };
        log("[TemplateSelector] Creating new template");
        onCreateNewTemplate(inputValue.trim());
        setSelectedTemplate(newTemplate);
        onTemplateSelect(newTemplate);
        setInputValue(newTemplate.name);
      }
      setIsSelecting(false);
      return;
    }

    // Find the selected template by ID
    const template = allTemplates.find((t) => t.id === selectedValue);
    if (template) {
      log("[TemplateSelector] Template matched by ID");
      setSelectedTemplate(template);
      onTemplateSelect(template);
      setInputValue(template.name);
    } else {
      // Fallback: try to find by name if ID doesn't match
      const templateByName = allTemplates.find((t) => t.name === selectedValue);
      if (templateByName) {
        log("[TemplateSelector] Template matched by name");
        setSelectedTemplate(templateByName);
        onTemplateSelect(templateByName);
        setInputValue(templateByName.name);
      } else {
        log(`[TemplateSelector] Template not found; available count=${allTemplates.length}`);
      }
    }
    
    setIsSelecting(false);
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    // Don't process input changes if we're in the middle of selecting an option
    if (isSelecting) {
      return;
    }
    
    const value = event.target.value;
    setInputValue(value);
    
    // Only clear selection if input is completely cleared
    // Don't clear if user is just typing to search
    if (!value.trim()) {
      setSelectedTemplate(null);
      onTemplateSelect(null);
    } else {
      // Check if the typed value exactly matches an existing template
      const exactMatch = allTemplates.find(
        (t) => t.name.toLowerCase() === value.toLowerCase()
      );
      if (exactMatch) {
        setSelectedTemplate(exactMatch);
        onTemplateSelect(exactMatch);
      } else if (selectedTemplate) {
        // If user is typing and it doesn't match current selection, clear it
        setSelectedTemplate(null);
        onTemplateSelect(null);
      }
    }
  };

  const handleFreeformSubmit = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (allowCreate && event.key === "Enter" && inputValue.trim() && !isExistingTemplate && onCreateNewTemplate) {
      const newTemplate: Template = {
        id: `new-${Date.now()}`,
        name: inputValue.trim(),
      };
      onCreateNewTemplate(inputValue.trim());
      setSelectedTemplate(newTemplate);
      onTemplateSelect(newTemplate);
    }
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent combobox dropdown from opening
    setInputValue("");
    setSelectedTemplate(null);
    onTemplateSelect(null);
  };

  const expandIconSlot = selectedTemplate ? (
    <span className={styles.expandIconWrapper}>
      <Dismiss16Regular
        onClick={handleClear}
        className={styles.clearIcon}
        title="Clear selection"
        aria-label="Clear template selection"
      />
      <ChevronDown20Regular />
    </span>
  ) : undefined;

  return (
    <div className={styles.container}>
      <Field className={styles.comboboxField} label={label} size="large">
        <Combobox
          freeform={allowCreate}
          value={inputValue}
          onOptionSelect={handleOptionSelect}
          onChange={handleInputChange}
          onKeyDown={handleFreeformSubmit}
          placeholder={allowCreate ? "Search templates or type to create new..." : "Search templates..."}
          size="large"
          className={styles.combobox}
          expandIcon={expandIconSlot}
        >
          {allowCreate && !isExistingTemplate && inputValue.trim() && onCreateNewTemplate && (
            <Option key="__CREATE_NEW__" value="__CREATE_NEW__" text={`Create new template: "${inputValue}"`}>
              Create new template: &quot;{inputValue}&quot;
            </Option>
          )}
          {filteredTemplates.map((template) => (
            <Option key={template.id} value={template.id} text={template.name}>
              {template.name}
            </Option>
          ))}
        </Combobox>
      </Field>
    </div>
  );
};

export default TemplateSelector;
