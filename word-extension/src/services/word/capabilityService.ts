export interface WordCapabilities {
  wordApi14: boolean;
  wordApi15: boolean;
  customXml: boolean;
  contentControlEvents: boolean;
  comments: boolean;
  compressedDocumentCapture: boolean;
  desktopTrackChanges: boolean;
}

function supports(setName: string, version?: string): boolean {
  try {
    return version
      ? !!Office?.context?.requirements?.isSetSupported?.(setName, version)
      : !!Office?.context?.requirements?.isSetSupported?.(setName);
  } catch {
    return false;
  }
}

export function getWordCapabilities(): WordCapabilities {
  const wordApi14 = supports("WordApi", "1.4");
  const wordApi15 = supports("WordApi", "1.5");
  const platform = Office?.context?.platform;
  const desktop = platform === Office.PlatformType.Mac || platform === Office.PlatformType.PC;
  return {
    wordApi14,
    wordApi15,
    customXml: supports("CustomXmlParts"),
    contentControlEvents: wordApi15,
    comments: wordApi14,
    compressedDocumentCapture: desktop && supports("CompressedFile"),
    desktopTrackChanges: supports("WordApiDesktop", "1.4"),
  };
}
