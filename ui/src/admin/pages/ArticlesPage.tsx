import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Eye,
  Heart,
  ImagePlus,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Send,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import {
  AreaStrip,
  EdButton,
  EditorialSelect,
  SlideSheet,
  ToggleSwitch,
} from "../components/EditorialPrimitives";
import {
  apiReq,
  apiUpload,
  applyAreaOrder,
  consumePendingArticleTarget,
  saveAreaOrder,
  type AreaItem,
} from "../lib/api";
import { useApp } from "../lib/context";

interface ArticleChannel {
  id: string;
  name: string;
  group?: string;
  type: string;
  secret?: boolean;
}

interface ArticleSection {
  id: number;
  name: string;
  sort?: number;
}

interface ArticleAttachment {
  attachmentType: string;
  resource: string;
  cover?: string;
  width?: number;
  height?: number;
  duration?: number;
  size?: number;
  previewUrl?: string;
}

interface ArticleRecord {
  articleId: string;
  areaId: string;
  channelId: string;
  sectionId: number;
  title: string;
  summary: string;
  content: string;
  cover?: { resource?: string; width?: number; height?: number } | null;
  authorUid: string;
  authorName?: string;
  authorAvatar?: string;
  isOwn?: boolean;
  canEdit?: boolean;
  likeCount: number;
  liked: boolean;
  commentCount: number;
  watchCount: number;
  isTop: boolean;
  state: string;
  publishTime: number;
  createdAt: number;
  updatedAt: number;
  showCover: boolean;
  attachments: ArticleAttachment[];
  ipAddress?: string;
}

interface CommentRecord {
  commentId: string;
  articleId: string;
  uid: string;
  authorName?: string;
  authorAvatar?: string;
  content: string;
  imageList: { url?: string; type?: string; width?: number; height?: number }[];
  parentId?: string;
  replyId?: string;
  replyToUid?: string;
  replyToName?: string;
  likeCount: number;
  childCount: number;
  liked: boolean;
  isArticleAuthor?: boolean;
  isOwn?: boolean;
  canDelete?: boolean;
  ipAddress?: string;
  createdAt: number;
  subCursor?: number;
  subComments?: CommentRecord[];
}

interface EditorState {
  mode: "create" | "edit";
  articleId?: string;
  title: string;
  content: string;
  sectionId: string;
  showCover: boolean;
  coverIndex: number;
  attachments: ArticleAttachment[];
}

function formatTime(raw: number | undefined): string {
  const value = Number(raw || 0);
  if (!value) return "";
  const ms = value > 1e11 ? value : value * 1000;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function stateLabel(state: string | undefined): { text: string; cls: string } | null {
  const upper = String(state || "").toUpperCase();
  if (!upper || upper === "PUBLISHED" || upper === "NORMAL") return null;
  if (upper === "AUDITING" || upper === "REVIEWING") return { text: "审核中", cls: "ed-tag--gold" };
  if (upper === "REJECTED" || upper === "BLOCKED") return { text: "未通过", cls: "ed-tag--err" };
  return { text: upper, cls: "ed-tag--muted" };
}

function normalizeResourcePath(raw: string | undefined): string {
  const text = String(raw || "").trim();
  if (!text) return "";
  if (/^https?:\/\//i.test(text)) {
    try {
      return new URL(text).pathname;
    } catch {
      return text.split("?")[0];
    }
  }
  return text.split("?")[0];
}

function isVideoPath(raw: string | undefined): boolean {
  const path = normalizeResourcePath(raw).toLowerCase();
  return /\.(mp4|webm|mov|m4v|mkv)$/.test(path);
}

function isVideoAttachment(att: ArticleAttachment): boolean {
  const type = String(att.attachmentType || "").toUpperCase();
  return type.includes("VIDEO") || isVideoPath(att.resource);
}

function resolveMediaSrc(att: ArticleAttachment): string {
  if (att.previewUrl) return att.previewUrl;
  if (att.resource && /^https?:\/\//i.test(att.resource)) return att.resource;
  return "";
}

function resolvePreviewImage(att: ArticleAttachment): string {
  if (att.previewUrl) return att.previewUrl;
  if (isVideoAttachment(att)) {
    if (att.cover && /^https?:\/\//i.test(att.cover)) return att.cover;
    return "";
  }
  return resolveMediaSrc(att);
}

function resolveCardCover(item: ArticleRecord): string {
  if (item.cover?.resource && /^https?:\/\//i.test(item.cover.resource) && !isVideoPath(item.cover.resource)) {
    return item.cover.resource;
  }
  for (const att of item.attachments || []) {
    const img = resolvePreviewImage(att);
    if (img) return img;
  }
  return "";
}

const INLINE_MEDIA_RE = /!\[([^\]]*)\]\(([^)\s]+)\)/g;

function cleanArticlePreview(raw: string | undefined): string {
  const text = String(raw || "");
  if (!text) return "";
  return text
    .replace(INLINE_MEDIA_RE, (_m, alt: string, path: string) => {
      const upperAlt = String(alt || "").toUpperCase();
      if (upperAlt.startsWith("VIDEO") || upperAlt.startsWith("SHORT_VIDEO") || isVideoPath(path)) {
        return "[视频]";
      }
      return "[图片]";
    })
    .replace(/\n{2,}/g, "\n")
    .trim();
}

type ContentBlock =
  | { kind: "text"; text: string }
  | { kind: "image"; src: string; alt: string }
  | { kind: "video"; src: string; poster?: string; alt: string };

function parseArticleDetailMedia(article: ArticleRecord): {
  blocks: ContentBlock[];
  remainingAttachments: ArticleAttachment[];
} {
  const attachments = Array.isArray(article.attachments) ? article.attachments : [];
  const byPath = new Map<string, ArticleAttachment>();
  for (const att of attachments) {
    const key = normalizeResourcePath(att.resource);
    if (key && !byPath.has(key)) byPath.set(key, att);
  }

  const rawContent = article.content || article.summary || "";
  const blocks: ContentBlock[] = [];
  const renderedPaths = new Set<string>();

  let lastIndex = 0;
  for (const match of rawContent.matchAll(INLINE_MEDIA_RE)) {
    const idx = match.index ?? 0;
    if (idx > lastIndex) {
      const chunk = rawContent.slice(lastIndex, idx).replace(/^\n+|\n+$/g, "");
      if (chunk.trim()) blocks.push({ kind: "text", text: chunk });
    }
    const alt = String(match[1] || "");
    const rawPath = String(match[2] || "");
    const normPath = normalizeResourcePath(rawPath);
    const matched = byPath.get(normPath);
    const isVideo =
      alt.toUpperCase().startsWith("VIDEO") ||
      alt.toUpperCase().startsWith("SHORT_VIDEO") ||
      isVideoPath(rawPath) ||
      (matched ? isVideoAttachment(matched) : false);
    const signedUrl = matched
      ? resolveMediaSrc(matched)
      : /^https?:\/\//i.test(rawPath)
        ? rawPath
        : "";

    if (signedUrl) {
      if (normPath) renderedPaths.add(normPath);
      if (isVideo) {
        blocks.push({
          kind: "video",
          src: signedUrl,
          poster: matched?.cover && /^https?:\/\//i.test(matched.cover) ? matched.cover : undefined,
          alt: alt || "帖子视频",
        });
      } else {
        blocks.push({ kind: "image", src: signedUrl, alt: alt || "帖子图片" });
      }
    } else {
      blocks.push({ kind: "text", text: isVideo ? "[视频]" : "[图片]" });
    }
    lastIndex = idx + match[0].length;
  }

  if (lastIndex < rawContent.length) {
    const tail = rawContent.slice(lastIndex).replace(/^\n+|\n+$/g, "");
    if (tail.trim()) blocks.push({ kind: "text", text: tail });
  }

  const remainingAttachments = attachments.filter((att) => {
    const key = normalizeResourcePath(att.resource);
    return !key || !renderedPaths.has(key);
  });

  return { blocks, remainingAttachments };
}

export function ArticlesPage() {
  const { setStatus, toast, confirm, navigate } = useApp();
  const searchId = useId();
  const titleId = useId();
  const contentId = useId();
  const newSectionId = useId();
  const commentInputId = useId();

  const [areas, setAreas] = useState<AreaItem[]>([]);
  const [currentArea, setCurrentArea] = useState("");
  const [channels, setChannels] = useState<ArticleChannel[]>([]);
  const [currentChannel, setCurrentChannel] = useState("");
  const [sections, setSections] = useState<ArticleSection[]>([]);
  const [sectionId, setSectionId] = useState<number>(0);

  const [articles, setArticles] = useState<ArticleRecord[]>([]);
  const [selfUid, setSelfUid] = useState("");
  const [nextCursor, setNextCursor] = useState(0);
  const [nextCursorState, setNextCursorState] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [keyword, setKeyword] = useState("");

  // Detail & comments drawer
  const [detailArticle, setDetailArticle] = useState<ArticleRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [comments, setComments] = useState<CommentRecord[]>([]);
  const [commentCount, setCommentCount] = useState(0);
  const [commentNextCursor, setCommentNextCursor] = useState(0);
  const [commentHasMore, setCommentHasMore] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [commentText, setCommentText] = useState("");
  const [commentImages, setCommentImages] = useState<ArticleAttachment[]>([]);
  const [replyTarget, setReplyTarget] = useState<CommentRecord | null>(null);
  const [uploadingCommentImg, setUploadingCommentImg] = useState(false);
  const [submittingComment, setSubmittingComment] = useState(false);
  const [loadingRepliesFor, setLoadingRepliesFor] = useState<Record<string, boolean>>({});

  // Create / Edit drawer
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [uploadingEditorImg, setUploadingEditorImg] = useState(false);
  const [submittingEditor, setSubmittingEditor] = useState(false);

  // Section management drawer
  const [sectionSheetOpen, setSectionSheetOpen] = useState(false);
  const [sectionDrafts, setSectionDrafts] = useState<Record<number, string>>({});
  const [newSectionName, setNewSectionName] = useState("");

  const listSeqRef = useRef(0);
  const channelSeqRef = useRef(0);
  const objectUrlsRef = useRef<string[]>([]);

  const trackObjectUrl = useCallback((url: string) => {
    objectUrlsRef.current.push(url);
    return url;
  }, []);

  useEffect(() => {
    return () => {
      for (const url of objectUrlsRef.current) {
        URL.revokeObjectURL(url);
      }
      objectUrlsRef.current = [];
    };
  }, []);

  const sectionNameMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const sec of sections) map.set(sec.id, sec.name);
    return map;
  }, [sections]);

  const loadArticles = useCallback(
    async (
      area: string,
      channel: string,
      secId: number,
      opts?: { append?: boolean; cursor?: number; cursorState?: string }
    ) => {
      if (!area || !channel) {
        setArticles([]);
        setHasMore(false);
        setNextCursor(0);
        setNextCursorState("");
        return;
      }
      const append = !!opts?.append;
      const seq = ++listSeqRef.current;
      if (append) setLoadingMore(true);
      else setLoadingList(true);
      try {
        const params = new URLSearchParams({
          area,
          channel,
          section_id: String(secId),
          cursor: String(opts?.cursor || 0),
        });
        if (opts?.cursorState) params.set("cursor_state", opts.cursorState);
        const res = await apiReq<any>(`/admin/api/articles?${params.toString()}`);
        if (seq !== listSeqRef.current) return;
        if (typeof res.selfUid === "string" && res.selfUid) setSelfUid(res.selfUid);
        const incoming: ArticleRecord[] = Array.isArray(res.items) ? res.items : [];
        setArticles((prev) => {
          if (!append) return incoming;
          const seen = new Set(prev.map((x) => x.articleId));
          return [...prev, ...incoming.filter((x) => !seen.has(x.articleId))];
        });
        setNextCursor(Number(res.nextCursor || 0));
        setNextCursorState(String(res.nextCursorState || ""));
        setHasMore(Boolean(res.hasMore));
        setStatus(`帖子 ${append ? "已加载更多" : `${incoming.length} 篇`}`, "success");
      } catch (e: any) {
        if (seq !== listSeqRef.current) return;
        if (!append) setArticles([]);
        toast(e.message || "加载帖子失败", "error");
        setStatus("帖子加载失败", "error");
      } finally {
        if (seq === listSeqRef.current) {
          setLoadingList(false);
          setLoadingMore(false);
        }
      }
    },
    [setStatus, toast]
  );

  const loadSections = useCallback(async (area: string, channel: string) => {
    if (!area || !channel) {
      setSections([]);
      return;
    }
    try {
      const res = await apiReq<any>(
        `/admin/api/articles/sections?area=${encodeURIComponent(area)}&channel=${encodeURIComponent(channel)}`
      );
      const list: ArticleSection[] = Array.isArray(res.sections) ? res.sections : [];
      setSections(list);
      setSectionDrafts(Object.fromEntries(list.map((s) => [s.id, s.name])));
    } catch {
      setSections([]);
    }
  }, []);

  const loadChannelsForArea = useCallback(
    async (area: string, preferredChannel?: string) => {
      if (!area) {
        setChannels([]);
        setCurrentChannel("");
        setSections([]);
        setArticles([]);
        return;
      }
      const seq = ++channelSeqRef.current;
      setLoadingChannels(true);
      try {
        const res = await apiReq<any>(`/admin/api/channels?area=${encodeURIComponent(area)}`);
        if (seq !== channelSeqRef.current) return;
        const all: ArticleChannel[] = Array.isArray(res.channels) ? res.channels : [];
        const artChannels = all.filter((c) => String(c.type || "").toUpperCase() === "ARTICLE");
        setChannels(artChannels);
        const target =
          (preferredChannel && artChannels.some((c) => c.id === preferredChannel) && preferredChannel) ||
          artChannels[0]?.id ||
          "";
        setCurrentChannel(target);
        setSectionId(0);
        setKeyword("");
        if (target) {
          await Promise.all([
            loadSections(area, target),
            loadArticles(area, target, 0),
          ]);
        } else {
          setSections([]);
          setArticles([]);
          setHasMore(false);
          setStatus("当前域暂无帖子频道", "neutral");
        }
      } catch (e: any) {
        if (seq !== channelSeqRef.current) return;
        toast(e.message || "加载频道失败", "error");
      } finally {
        if (seq === channelSeqRef.current) setLoadingChannels(false);
      }
    },
    [loadArticles, loadSections, setStatus, toast]
  );

  const loadAll = useCallback(async () => {
    try {
      const pending = consumePendingArticleTarget();
      const res = await apiReq<any>("/admin/api/areas");
      const ordered = applyAreaOrder<AreaItem>(res.areas || []);
      setAreas(ordered);
      const nextArea =
        (pending?.area && ordered.some((a) => a.id === pending.area) && pending.area) ||
        (currentArea && ordered.some((a) => a.id === currentArea) && currentArea) ||
        ordered[0]?.id ||
        "";
      setCurrentArea(nextArea);
      if (nextArea) {
        await loadChannelsForArea(nextArea, pending?.channel || currentChannel);
      }
    } catch (e: any) {
      toast(e.message || "加载域列表失败", "error");
    }
  }, [currentArea, currentChannel, loadChannelsForArea, toast]);

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelectChannel = async (channelId: string, btn?: HTMLButtonElement | null) => {
    if (btn) {
      btn.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    setCurrentChannel(channelId);
    setSectionId(0);
    setKeyword("");
    await Promise.all([
      loadSections(currentArea, channelId),
      loadArticles(currentArea, channelId, 0),
    ]);
  };

  const handleSelectSection = async (nextSec: number) => {
    setSectionId(nextSec);
    await loadArticles(currentArea, currentChannel, nextSec);
  };

  const loadComments = useCallback(
    async (area: string, channel: string, articleId: string, opts?: { append?: boolean; cursor?: number }) => {
      const append = !!opts?.append;
      setCommentsLoading(true);
      try {
        const params = new URLSearchParams({
          area,
          channel,
          cursor: String(opts?.cursor || 0),
          page_size: "30",
        });
        const res = await apiReq<any>(
          `/admin/api/articles/${encodeURIComponent(articleId)}/comments?${params.toString()}`
        );
        if (typeof res.selfUid === "string" && res.selfUid) setSelfUid(res.selfUid);
        const incoming: CommentRecord[] = Array.isArray(res.items) ? res.items : [];
        setComments((prev) => {
          if (!append) return incoming;
          const seen = new Set(prev.map((c) => c.commentId));
          return [...prev, ...incoming.filter((c) => !seen.has(c.commentId))];
        });
        setCommentCount(Number(res.commentCount || incoming.length));
        setCommentNextCursor(Number(res.nextCursor || 0));
        setCommentHasMore(Boolean(res.hasMore));
      } catch (e: any) {
        toast(e.message || "加载评论失败", "error");
      } finally {
        setCommentsLoading(false);
      }
    },
    [toast]
  );

  const openDetail = async (item: ArticleRecord) => {
    setDetailArticle(item);
    setComments([]);
    setCommentCount(item.commentCount || 0);
    setCommentText("");
    setCommentImages([]);
    setReplyTarget(null);
    setDetailLoading(true);
    try {
      const [detailRes] = await Promise.all([
        apiReq<any>(
          `/admin/api/articles/${encodeURIComponent(item.articleId)}?area=${encodeURIComponent(currentArea)}&channel=${encodeURIComponent(currentChannel)}`
        ),
        loadComments(currentArea, currentChannel, item.articleId),
      ]);
      if (detailRes.selfUid) setSelfUid(String(detailRes.selfUid));
      if (detailRes.article) {
        setDetailArticle(detailRes.article);
      }
    } catch (e: any) {
      toast(e.message || "加载帖子详情失败", "error");
    } finally {
      setDetailLoading(false);
    }
  };

  const toggleLikeArticle = async (item: ArticleRecord) => {
    const nextLiked = !item.liked;
    try {
      await apiReq(`/admin/api/articles/${encodeURIComponent(item.articleId)}/like`, {
        method: "POST",
        body: JSON.stringify({ area: currentArea, channel: currentChannel, liked: nextLiked }),
      });
      const patchItem = (a: ArticleRecord) =>
        a.articleId === item.articleId
          ? { ...a, liked: nextLiked, likeCount: Math.max(0, (a.likeCount || 0) + (nextLiked ? 1 : -1)) }
          : a;
      setArticles((prev) => prev.map(patchItem));
      setDetailArticle((prev) => (prev ? patchItem(prev) : prev));
    } catch (e: any) {
      toast(e.message || "点赞操作失败", "error");
    }
  };

  const deleteArticle = async (item: ArticleRecord) => {
    const ok = await confirm("删除帖子", `确认删除帖子「${item.title || item.articleId}」？此操作不可撤销。`, {
      okText: "确认删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await apiReq(`/admin/api/articles/${encodeURIComponent(item.articleId)}`, {
        method: "DELETE",
        body: JSON.stringify({ area: currentArea, channel: currentChannel }),
      });
      toast("帖子已删除", "warning");
      setArticles((prev) => prev.filter((a) => a.articleId !== item.articleId));
      if (detailArticle?.articleId === item.articleId) setDetailArticle(null);
    } catch (e: any) {
      toast(e.message || "删除帖子失败", "error");
    }
  };

  const openCreateEditor = () => {
    if (!currentArea || !currentChannel) {
      toast("请先选择一个帖子频道", "warning");
      return;
    }
    setEditor({
      mode: "create",
      title: "",
      content: "",
      sectionId: sectionId > 0 ? String(sectionId) : "0",
      showCover: true,
      coverIndex: 0,
      attachments: [],
    });
  };

  const canEditArticle = useCallback(
    (item: ArticleRecord | null | undefined): boolean => {
      if (!item) return false;
      if (typeof item.canEdit === "boolean") return item.canEdit;
      return Boolean(selfUid && item.authorUid && item.authorUid === selfUid);
    },
    [selfUid]
  );

  const openEditEditor = async (item: ArticleRecord) => {
    if (!canEditArticle(item)) {
      toast("仅支持编辑 Bot 自己发布的帖子", "warning");
      return;
    }
    try {
      const res = await apiReq<any>(
        `/admin/api/articles/${encodeURIComponent(item.articleId)}?area=${encodeURIComponent(currentArea)}&channel=${encodeURIComponent(currentChannel)}`
      );
      const full: ArticleRecord = res.article || item;
      const atts: ArticleAttachment[] = Array.isArray(full.attachments)
        ? full.attachments.map((att) => ({ ...att, previewUrl: resolvePreviewImage(att) }))
        : [];
      let coverIdx = 0;
      if (full.cover?.resource && atts.length > 0) {
        const hit = atts.findIndex((a) => a.resource === full.cover?.resource);
        if (hit >= 0) coverIdx = hit;
      }
      setEditor({
        mode: "edit",
        articleId: full.articleId,
        title: full.title || "",
        content: full.content || "",
        sectionId: String(full.sectionId || 0),
        showCover: full.showCover !== false,
        coverIndex: coverIdx,
        attachments: atts,
      });
    } catch (e: any) {
      toast(e.message || "读取原帖详情失败", "error");
    }
  };

  const uploadImages = async (
    files: FileList | null,
    onDone: (uploaded: ArticleAttachment[]) => void,
    setBusy: (b: boolean) => void
  ) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    const uploaded: ArticleAttachment[] = [];
    try {
      for (const file of Array.from(files)) {
        const fd = new FormData();
        fd.append("area", currentArea);
        fd.append("channel", currentChannel);
        fd.append("file", file);
        const res = await apiUpload<any>("/admin/api/articles/upload-image", fd);
        if (res.attachment) {
          uploaded.push({
            ...res.attachment,
            previewUrl: trackObjectUrl(URL.createObjectURL(file)),
          });
        }
      }
      if (uploaded.length > 0) {
        onDone(uploaded);
        toast(`已上传 ${uploaded.length} 张图片`, "success");
      }
    } catch (e: any) {
      toast(e.message || "图片上传失败", "error");
    } finally {
      setBusy(false);
    }
  };

  const submitEditor = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editor || submittingEditor) return;
    if (!editor.title.trim()) {
      toast("帖子标题不能为空", "warning");
      return;
    }
    setSubmittingEditor(true);
    const cleanAttachments = editor.attachments.map(({ previewUrl: _preview, ...rest }) => rest);
    const payload = {
      area: currentArea,
      channel: currentChannel,
      title: editor.title.trim(),
      content: editor.content,
      sectionId: Number(editor.sectionId) || 0,
      showCover: editor.showCover,
      coverIndex: cleanAttachments.length > 0 ? Math.min(editor.coverIndex, cleanAttachments.length - 1) : 0,
      attachments: cleanAttachments,
    };
    try {
      if (editor.mode === "create") {
        await apiReq("/admin/api/articles", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast("帖子已发布", "success");
      } else if (editor.articleId) {
        await apiReq(`/admin/api/articles/${encodeURIComponent(editor.articleId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast("帖子已更新", "success");
      }
      const editedId = editor.articleId;
      setEditor(null);
      await loadArticles(currentArea, currentChannel, sectionId);
      if (editedId && detailArticle?.articleId === editedId) {
        const refreshed = await apiReq<any>(
          `/admin/api/articles/${encodeURIComponent(editedId)}?area=${encodeURIComponent(currentArea)}&channel=${encodeURIComponent(currentChannel)}`
        );
        if (refreshed.article) setDetailArticle(refreshed.article);
      }
    } catch (err: any) {
      toast(err.message || "保存帖子失败", "error");
    } finally {
      setSubmittingEditor(false);
    }
  };

  const submitComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!detailArticle || submittingComment) return;
    if (!commentText.trim() && commentImages.length === 0) {
      toast("请输入评论内容或上传图片", "warning");
      return;
    }
    setSubmittingComment(true);
    try {
      await apiReq(`/admin/api/articles/${encodeURIComponent(detailArticle.articleId)}/comments`, {
        method: "POST",
        body: JSON.stringify({
          area: currentArea,
          channel: currentChannel,
          content: commentText.trim(),
          parentId: replyTarget ? (replyTarget.parentId || replyTarget.commentId) : "",
          replyId: replyTarget ? replyTarget.commentId : "",
          imageList: commentImages.map((img) => img.resource),
        }),
      });
      setCommentText("");
      setCommentImages([]);
      setReplyTarget(null);
      toast("评论已发表", "success");
      await loadComments(currentArea, currentChannel, detailArticle.articleId);
      setArticles((prev) =>
        prev.map((a) =>
          a.articleId === detailArticle.articleId ? { ...a, commentCount: (a.commentCount || 0) + 1 } : a
        )
      );
      setDetailArticle((prev) => (prev ? { ...prev, commentCount: (prev.commentCount || 0) + 1 } : prev));
    } catch (err: any) {
      toast(err.message || "发表评论失败", "error");
    } finally {
      setSubmittingComment(false);
    }
  };

  const canDeleteComment = useCallback(
    (comment: CommentRecord | null | undefined): boolean => {
      if (!comment) return false;
      if (typeof comment.canDelete === "boolean") return comment.canDelete;
      return Boolean(selfUid && comment.uid && comment.uid === selfUid);
    },
    [selfUid]
  );

  const loadMoreReplies = async (parent: CommentRecord) => {
    if (!detailArticle || loadingRepliesFor[parent.commentId]) return;
    setLoadingRepliesFor((prev) => ({ ...prev, [parent.commentId]: true }));
    try {
      const params = new URLSearchParams({
        area: currentArea,
        channel: currentChannel,
        cursor: "0",
        page_size: "50",
      });
      const res = await apiReq<any>(
        `/admin/api/articles/${encodeURIComponent(detailArticle.articleId)}/comments/${encodeURIComponent(parent.commentId)}/replies?${params.toString()}`
      );
      const fetched: CommentRecord[] = Array.isArray(res.items) ? res.items : [];
      setComments((prev) =>
        prev.map((c) => {
          if (c.commentId !== parent.commentId) return c;
          const mergedMap = new Map<string, CommentRecord>();
          for (const existing of c.subComments || []) mergedMap.set(existing.commentId, existing);
          for (const item of fetched) mergedMap.set(item.commentId, item);
          const merged = Array.from(mergedMap.values()).sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
          return {
            ...c,
            childCount: Math.max(c.childCount || 0, Number(res.childCount || merged.length)),
            subComments: merged,
            subCursor: Number(res.nextCursor || 0),
          };
        })
      );
    } catch (err: any) {
      toast(err.message || "加载回复列表失败", "error");
    } finally {
      setLoadingRepliesFor((prev) => ({ ...prev, [parent.commentId]: false }));
    }
  };

  const deleteComment = async (comment: CommentRecord) => {
    if (!detailArticle) return;
    if (!canDeleteComment(comment)) {
      toast("仅支持删除 Bot 自己发表的评论", "warning");
      return;
    }
    const ok = await confirm("删除评论", "确认删除该条评论？", { okText: "确认删除", danger: true });
    if (!ok) return;
    try {
      await apiReq(
        `/admin/api/articles/${encodeURIComponent(detailArticle.articleId)}/comments/${encodeURIComponent(comment.commentId)}`,
        {
          method: "DELETE",
          body: JSON.stringify({ area: currentArea, channel: currentChannel }),
        }
      );
      toast("评论已删除", "warning");
      const isSub = Boolean(comment.parentId);
      setComments((prev) =>
        isSub
          ? prev.map((parent) =>
              parent.commentId === comment.parentId
                ? {
                    ...parent,
                    childCount: Math.max(0, (parent.childCount || 0) - 1),
                    subComments: (parent.subComments || []).filter((s) => s.commentId !== comment.commentId),
                  }
                : parent
            )
          : prev.filter((c) => c.commentId !== comment.commentId)
      );
      setCommentCount((c) => Math.max(0, c - 1));
      setArticles((prev) =>
        prev.map((a) =>
          a.articleId === detailArticle.articleId
            ? { ...a, commentCount: Math.max(0, (a.commentCount || 0) - 1) }
            : a
        )
      );
      setDetailArticle((prev) =>
        prev ? { ...prev, commentCount: Math.max(0, (prev.commentCount || 0) - 1) } : prev
      );
    } catch (err: any) {
      toast(err.message || "删除评论失败", "error");
    }
  };

  const toggleLikeComment = async (comment: CommentRecord) => {
    if (!detailArticle) return;
    const nextLiked = !comment.liked;
    try {
      await apiReq(
        `/admin/api/articles/${encodeURIComponent(detailArticle.articleId)}/comments/${encodeURIComponent(comment.commentId)}/like`,
        {
          method: "POST",
          body: JSON.stringify({ area: currentArea, channel: currentChannel, liked: nextLiked }),
        }
      );
      const patchOne = (c: CommentRecord): CommentRecord =>
        c.commentId === comment.commentId
          ? { ...c, liked: nextLiked, likeCount: Math.max(0, (c.likeCount || 0) + (nextLiked ? 1 : -1)) }
          : {
              ...c,
              subComments: (c.subComments || []).map((s) =>
                s.commentId === comment.commentId
                  ? { ...s, liked: nextLiked, likeCount: Math.max(0, (s.likeCount || 0) + (nextLiked ? 1 : -1)) }
                  : s
              ),
            };
      setComments((prev) => prev.map(patchOne));
    } catch (err: any) {
      toast(err.message || "评论点赞失败", "error");
    }
  };

  const createSection = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newSectionName.trim();
    if (!name) {
      toast("分区名称不能为空", "warning");
      return;
    }
    try {
      await apiReq("/admin/api/articles/sections", {
        method: "POST",
        body: JSON.stringify({ area: currentArea, channel: currentChannel, name }),
      });
      setNewSectionName("");
      toast("分区已创建", "success");
      await loadSections(currentArea, currentChannel);
    } catch (err: any) {
      toast(err.message || "创建分区失败", "error");
    }
  };

  const saveSectionName = async (sec: ArticleSection) => {
    const name = (sectionDrafts[sec.id] || "").trim();
    if (!name) {
      toast("分区名称不能为空", "warning");
      return;
    }
    try {
      await apiReq(`/admin/api/articles/sections/${sec.id}`, {
        method: "PUT",
        body: JSON.stringify({ area: currentArea, channel: currentChannel, name }),
      });
      toast("分区名称已更新", "success");
      await loadSections(currentArea, currentChannel);
    } catch (err: any) {
      toast(err.message || "更新分区失败", "error");
    }
  };

  const deleteSection = async (sec: ArticleSection) => {
    const ok = await confirm("删除分区", `确认删除分区「${sec.name}」？`, { okText: "确认删除", danger: true });
    if (!ok) return;
    try {
      await apiReq(`/admin/api/articles/sections/${sec.id}`, {
        method: "DELETE",
        body: JSON.stringify({ area: currentArea, channel: currentChannel }),
      });
      toast("分区已删除", "warning");
      if (sectionId === sec.id) {
        setSectionId(0);
        await loadArticles(currentArea, currentChannel, 0);
      }
      await loadSections(currentArea, currentChannel);
    } catch (err: any) {
      toast(err.message || "删除分区失败", "error");
    }
  };

  const filteredArticles = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return articles;
    return articles.filter((a) => {
      const hay = `${a.title} ${a.summary} ${a.content} ${a.authorName || ""} ${a.articleId}`.toLowerCase();
      return hay.includes(q);
    });
  }, [articles, keyword]);

  const sectionOptions = useMemo(
    () => [
      { value: "0", label: "不指定分区" },
      ...sections.map((s) => ({ value: String(s.id), label: s.name })),
    ],
    [sections]
  );

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">帖子管理</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton
            size="sm"
            variant="ghost"
            onClick={() => loadArticles(currentArea, currentChannel, sectionId)}
            disabled={!currentChannel}
          >
            <RefreshCw size={13} style={{ marginInlineEnd: 5 }} />
            刷新
          </EdButton>
          <EdButton
            size="sm"
            variant="ghost"
            onClick={() => setSectionSheetOpen(true)}
            disabled={!currentChannel}
          >
            <SlidersHorizontal size={13} style={{ marginInlineEnd: 5 }} />
            分区管理
          </EdButton>
          <EdButton size="sm" variant="primary" onClick={openCreateEditor} disabled={!currentChannel}>
            <Plus size={14} style={{ marginInlineEnd: 4 }} />
            发布帖子
          </EdButton>
        </div>
      </div>

      <AreaStrip
        areas={areas}
        value={currentArea}
        onChange={(id) => {
          setCurrentArea(id);
          loadChannelsForArea(id);
        }}
        onReorder={(next) => {
          setAreas(next);
          saveAreaOrder(next.map((a) => a.id));
        }}
      />

      <section className="ed-cell ed-article-toolbar">
        {loadingChannels ? (
          <div style={{ fontSize: 13, color: "var(--ink-faint)" }}>正在加载帖子频道...</div>
        ) : channels.length === 0 ? (
          <div className="ed-empty" style={{ padding: "26px 12px" }}>
            <div style={{ marginBottom: 12 }}>当前域还没有帖子频道</div>
            <EdButton size="sm" variant="primary" onClick={() => navigate("areas")}>
              前往域管理创建帖子频道
            </EdButton>
          </div>
        ) : (
          <>
            <div className="ed-article-tablist" role="tablist" aria-label="帖子频道">
              {channels.map((ch) => {
                const active = ch.id === currentChannel;
                return (
                  <button
                    key={ch.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className="ed-article-tab"
                    onClick={(e) => handleSelectChannel(ch.id, e.currentTarget)}
                  >
                    <span>{ch.name}</span>
                    {ch.secret && <span className="ed-tag ed-tag--err">私密</span>}
                  </button>
                );
              })}
            </div>

            <div className="ed-article-filters">
              <div className="ed-article-pills" role="group" aria-label="帖子分区筛选">
                <button
                  type="button"
                  className="ed-article-pill"
                  aria-pressed={sectionId === 0}
                  onClick={() => handleSelectSection(0)}
                >
                  全部
                </button>
                <button
                  type="button"
                  className="ed-article-pill"
                  aria-pressed={sectionId === -1}
                  onClick={() => handleSelectSection(-1)}
                >
                  Bot 发布
                </button>
                {sections.map((sec) => (
                  <button
                    key={sec.id}
                    type="button"
                    className="ed-article-pill"
                    aria-pressed={sectionId === sec.id}
                    onClick={() => handleSelectSection(sec.id)}
                  >
                    {sec.name}
                  </button>
                ))}
              </div>

              <search className="ed-article-search">
                <label htmlFor={searchId} className="ed-visually-hidden">
                  筛选已加载帖子
                </label>
                <Search size={14} style={{ color: "var(--ink-faint)", flexShrink: 0 }} aria-hidden="true" />
                <input
                  id={searchId}
                  type="search"
                  className="ed-input"
                  value={keyword}
                  placeholder="筛选标题、正文或作者..."
                  onChange={(e) => setKeyword(e.target.value)}
                />
              </search>
            </div>
          </>
        )}
      </section>

      {currentChannel && (
        <section>
          {loadingList ? (
            <div className="ed-article-grid" aria-busy="true">
              {[1, 2, 3, 4, 5, 6].map((idx) => (
                <div key={idx} className="ed-article-skeleton" />
              ))}
            </div>
          ) : filteredArticles.length === 0 ? (
            <div className="ed-cell ed-empty" style={{ padding: "48px 18px" }}>
              {keyword.trim() ? "没有匹配的帖子" : "该分区暂无帖子"}
            </div>
          ) : (
            <>
              <div className="ed-article-grid">
                {filteredArticles.map((item) => {
                  const coverSrc = resolveCardCover(item);
                  const previewText = cleanArticlePreview(item.summary || item.content);
                  const badge = stateLabel(item.state);
                  const secName = item.sectionId ? sectionNameMap.get(item.sectionId) : "";
                  const canEdit = canEditArticle(item);
                  const isOwnPost = Boolean(item.isOwn || canEdit);
                  return (
                    <article key={item.articleId} className="ed-article-card">
                      {coverSrc && (
                        <div className="ed-article-card__cover" onClick={() => openDetail(item)}>
                          <img src={coverSrc} alt={item.title || "帖子封面"} loading="lazy" />
                        </div>
                      )}
                      <div className="ed-article-card__body">
                        {(item.isTop || isOwnPost || secName || badge) && (
                          <div className="ed-article-card__badges">
                            {item.isTop && <span className="ed-tag ed-tag--gold">置顶</span>}
                            {isOwnPost && <span className="ed-tag ed-tag--ok">Bot</span>}
                            {secName && <span className="ed-tag">{secName}</span>}
                            {badge && <span className={`ed-tag ${badge.cls}`}>{badge.text}</span>}
                          </div>
                        )}
                        <h3 className="ed-article-card__title" onClick={() => openDetail(item)}>
                          {item.title || "(无标题)"}
                        </h3>
                        {previewText && (
                          <p className="ed-article-card__summary">{previewText}</p>
                        )}
                        <div className="ed-article-card__meta">
                          <div className="ed-article-author">
                            {item.authorAvatar && (
                              <img src={item.authorAvatar} alt="" className="ed-article-author__avatar" loading="lazy" />
                            )}
                            <span className="ed-article-author__name">{item.authorName || item.authorUid.slice(0, 8)}</span>
                            <span>{formatTime(item.publishTime || item.createdAt)}</span>
                          </div>
                          <div className="ed-article-stats">
                            <span className="ed-article-stat" title="点赞">
                              <Heart size={12} fill={item.liked ? "currentColor" : "none"} />
                              {item.likeCount}
                            </span>
                            <span className="ed-article-stat" title="评论">
                              <MessageSquare size={12} />
                              {item.commentCount}
                            </span>
                            <span className="ed-article-stat" title="浏览">
                              <Eye size={12} />
                              {item.watchCount}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="ed-article-card__foot">
                        <div style={{ display: "flex", gap: 6 }}>
                          <EdButton size="sm" variant="ghost" onClick={() => openDetail(item)}>
                            查看
                          </EdButton>
                          {canEdit && (
                            <EdButton size="sm" variant="ghost" onClick={() => openEditEditor(item)}>
                              <Pencil size={12} style={{ marginInlineEnd: 4 }} />
                              编辑
                            </EdButton>
                          )}
                          <EdButton
                            size="sm"
                            variant={item.liked ? "primary" : "ghost"}
                            onClick={() => toggleLikeArticle(item)}
                          >
                            <Heart size={12} fill={item.liked ? "currentColor" : "none"} style={{ marginInlineEnd: 4 }} />
                            {item.liked ? "已赞" : "点赞"}
                          </EdButton>
                        </div>
                        <EdButton size="sm" variant="danger" onClick={() => deleteArticle(item)}>
                          <Trash2 size={12} />
                        </EdButton>
                      </div>
                    </article>
                  );
                })}
              </div>

              {hasMore && (
                <div style={{ display: "flex", justifyContent: "center", marginTop: 18 }}>
                  <EdButton
                    variant="ghost"
                    disabled={loadingMore}
                    onClick={() =>
                      loadArticles(currentArea, currentChannel, sectionId, {
                        append: true,
                        cursor: nextCursor,
                        cursorState: nextCursorState,
                      })
                    }
                  >
                    {loadingMore ? "加载中..." : "加载更多帖子"}
                  </EdButton>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {/* Article Detail & Comments Sheet */}
      <SlideSheet
        open={!!detailArticle}
        wide
        title={detailArticle?.title || "帖子详情"}
        onClose={() => setDetailArticle(null)}
        footer={
          detailArticle && (
            <>
              <EdButton
                variant={detailArticle.liked ? "primary" : "ghost"}
                onClick={() => toggleLikeArticle(detailArticle)}
              >
                <Heart size={13} fill={detailArticle.liked ? "currentColor" : "none"} style={{ marginInlineEnd: 5 }} />
                {detailArticle.liked ? `已赞 (${detailArticle.likeCount})` : `点赞 (${detailArticle.likeCount})`}
              </EdButton>
              {canEditArticle(detailArticle) && (
                <EdButton variant="ghost" onClick={() => openEditEditor(detailArticle)}>
                  <Pencil size={13} style={{ marginInlineEnd: 5 }} />
                  编辑帖子
                </EdButton>
              )}
              <EdButton variant="danger" onClick={() => deleteArticle(detailArticle)}>
                <Trash2 size={13} style={{ marginInlineEnd: 5 }} />
                删除帖子
              </EdButton>
            </>
          )
        }
      >
        {detailArticle && (
          <div style={{ display: "grid", gap: 18 }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <div className="ed-article-author">
                {detailArticle.authorAvatar && (
                  <img src={detailArticle.authorAvatar} alt="" className="ed-article-author__avatar" />
                )}
                <span className="ed-article-author__name">
                  {detailArticle.authorName || detailArticle.authorUid}
                </span>
                <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
                  {formatTime(detailArticle.publishTime || detailArticle.createdAt)}
                </span>
                {detailArticle.ipAddress && (
                  <span style={{ fontSize: 11.5, color: "var(--ink-faint)" }}>· {detailArticle.ipAddress}</span>
                )}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {detailArticle.isTop && <span className="ed-tag ed-tag--gold">置顶</span>}
                {detailArticle.sectionId > 0 && sectionNameMap.get(detailArticle.sectionId) && (
                  <span className="ed-tag">{sectionNameMap.get(detailArticle.sectionId)}</span>
                )}
                {stateLabel(detailArticle.state) && (
                  <span className={`ed-tag ${stateLabel(detailArticle.state)!.cls}`}>
                    {stateLabel(detailArticle.state)!.text}
                  </span>
                )}
                <span className="ed-tag ed-tag--muted">浏览 {detailArticle.watchCount}</span>
              </div>
            </div>

            {detailLoading ? (
              <div style={{ fontSize: 13, color: "var(--ink-faint)" }}>正在拉取完整内容...</div>
            ) : (() => {
              const { blocks, remainingAttachments } = parseArticleDetailMedia(detailArticle);
              return (
                <>
                  <div className="ed-article-detail__content">
                    {blocks.length === 0 ? (
                      <div className="ed-article-detail__text">（无正文内容）</div>
                    ) : (
                      blocks.map((block, idx) => {
                        if (block.kind === "text") {
                          return (
                            <div key={`txt-${idx}`} className="ed-article-detail__text">
                              {block.text}
                            </div>
                          );
                        }
                        if (block.kind === "video") {
                          return (
                            <div key={`vid-${idx}`} className="ed-article-inline-media">
                              <video
                                controls
                                playsInline
                                preload="metadata"
                                poster={block.poster}
                                src={block.src}
                              />
                            </div>
                          );
                        }
                        return (
                          <a
                            key={`img-${idx}`}
                            href={block.src}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ed-article-inline-media"
                            title="点击新窗口查看原图"
                          >
                            <img src={block.src} alt={block.alt} loading="lazy" />
                          </a>
                        );
                      })
                    )}
                  </div>

                  {remainingAttachments.length > 0 && (
                    <div className="ed-article-media-grid">
                      {remainingAttachments.map((att, idx) => {
                        const src = resolveMediaSrc(att);
                        if (!src) return null;
                        if (isVideoAttachment(att)) {
                          return (
                            <div key={`${att.resource}-${idx}`} className="ed-article-media-item">
                              <video
                                controls
                                playsInline
                                preload="metadata"
                                poster={att.cover && /^https?:\/\//i.test(att.cover) ? att.cover : undefined}
                                src={src}
                              />
                            </div>
                          );
                        }
                        return (
                          <a
                            key={`${att.resource}-${idx}`}
                            href={src}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ed-article-media-item"
                            title="点击新窗口查看原图"
                          >
                            <img src={src} alt={`附件 ${idx + 1}`} loading="lazy" />
                          </a>
                        );
                      })}
                    </div>
                  )}
                </>
              );
            })()}

            <div style={{ display: "grid", gap: 12, paddingTop: 6, borderTop: "1px solid var(--rule)" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div className="ed-label">
                  <span>COMMENTS</span>
                  <span className="ed-label__zh">评论 ({commentCount})</span>
                </div>
                <EdButton
                  size="sm"
                  variant="ghost"
                  onClick={() => loadComments(currentArea, currentChannel, detailArticle.articleId)}
                >
                  刷新评论
                </EdButton>
              </div>

              <form onSubmit={submitComment} style={{ display: "grid", gap: 10 }}>
                {replyTarget && (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12.5, color: "var(--accent-hover)", padding: "6px 10px", borderRadius: 10, background: "var(--accent-soft)" }}>
                    <span>回复 @{replyTarget.authorName || replyTarget.uid.slice(0, 8)}</span>
                    <button
                      type="button"
                      className="ed-sheet__close"
                      style={{ width: 22, height: 22 }}
                      onClick={() => setReplyTarget(null)}
                      aria-label="取消回复"
                    >
                      <X size={12} />
                    </button>
                  </div>
                )}
                <label htmlFor={commentInputId} className="ed-visually-hidden">
                  评论内容
                </label>
                <textarea
                  id={commentInputId}
                  className="ed-input"
                  rows={2}
                  style={{ resize: "vertical" }}
                  value={commentText}
                  placeholder={replyTarget ? `回复 ${replyTarget.authorName || ""}...` : "发表评论（Ctrl+Enter 快速提交）..."}
                  onChange={(e) => setCommentText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.nativeEvent.isComposing) return;
                    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                      e.preventDefault();
                      void submitComment(e as unknown as React.FormEvent);
                    }
                  }}
                />
                {commentImages.length > 0 && (
                  <div className="ed-article-media-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(92px, 1fr))" }}>
                    {commentImages.map((img, idx) => (
                      <div key={`${img.resource}-${idx}`} className="ed-article-media-item">
                        {img.previewUrl && <img src={img.previewUrl} alt={`评论图片 ${idx + 1}`} />}
                        <div className="ed-article-media-item__bar">
                          <span style={{ fontSize: 10, color: "#fff" }}>图 {idx + 1}</span>
                          <button
                            type="button"
                            className="ed-sheet__close"
                            style={{ width: 20, height: 20 }}
                            onClick={() => setCommentImages((prev) => prev.filter((_, i) => i !== idx))}
                            aria-label="移除图片"
                          >
                            <X size={11} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <label className="ed-article-upload-label">
                    <input
                      type="file"
                      accept="image/*"
                      multiple
                      className="ed-visually-hidden"
                      disabled={uploadingCommentImg}
                      onChange={(e) => {
                        const files = e.currentTarget.files;
                        void uploadImages(
                          files,
                          (items) => setCommentImages((prev) => [...prev, ...items]),
                          setUploadingCommentImg
                        );
                        e.currentTarget.value = "";
                      }}
                    />
                    <ImagePlus size={14} aria-hidden="true" />
                    <span>{uploadingCommentImg ? "上传中..." : "添加图片"}</span>
                  </label>
                  <EdButton type="submit" size="sm" variant="primary" disabled={submittingComment}>
                    <Send size={12} style={{ marginInlineEnd: 5 }} />
                    {submittingComment ? "发送中..." : replyTarget ? "发送回复" : "发表评论"}
                  </EdButton>
                </div>
              </form>

              <div className="ed-article-comments">
                {commentsLoading && comments.length === 0 ? (
                  <div style={{ fontSize: 13, color: "var(--ink-faint)", padding: "12px 0" }}>正在加载评论...</div>
                ) : comments.length === 0 ? (
                  <div className="ed-empty" style={{ padding: "18px 0" }}>暂无评论</div>
                ) : (
                  comments.map((c) => {
                    const subs = Array.isArray(c.subComments) ? c.subComments : [];
                    const remainingSubs = Math.max(0, (c.childCount || 0) - subs.length);
                    return (
                      <div key={c.commentId} className="ed-article-comment">
                        <div className="ed-article-comment__head">
                          <div className="ed-article-author">
                            {c.authorAvatar && (
                              <img src={c.authorAvatar} alt="" className="ed-article-author__avatar" loading="lazy" />
                            )}
                            <span className="ed-article-author__name">{c.authorName || c.uid.slice(0, 8)}</span>
                            {c.isOwn && <span className="ed-tag ed-tag--ok">Bot</span>}
                            {c.isArticleAuthor && <span className="ed-tag ed-tag--gold">作者</span>}
                            {c.replyToName && (
                              <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>回复 @{c.replyToName}</span>
                            )}
                          </div>
                          <span style={{ fontSize: 11.5, color: "var(--ink-faint)" }}>
                            {formatTime(c.createdAt)}
                          </span>
                        </div>

                        {c.content && <p className="ed-article-comment__text">{c.content}</p>}

                        {c.imageList && c.imageList.length > 0 && (
                          <div className="ed-article-media-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(100px, 1fr))" }}>
                            {c.imageList.map((img, idx) =>
                              img.url ? (
                                <a
                                  key={`${img.url}-${idx}`}
                                  href={img.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="ed-article-media-item"
                                >
                                  <img src={img.url} alt={`评论配图 ${idx + 1}`} loading="lazy" />
                                </a>
                              ) : null
                            )}
                          </div>
                        )}

                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                          <div style={{ display: "flex", gap: 6 }}>
                            <EdButton
                              size="sm"
                              variant={c.liked ? "primary" : "ghost"}
                              onClick={() => toggleLikeComment(c)}
                            >
                              <Heart size={11} fill={c.liked ? "currentColor" : "none"} style={{ marginInlineEnd: 4 }} />
                              {c.likeCount}
                            </EdButton>
                            <EdButton size="sm" variant="ghost" onClick={() => setReplyTarget(c)}>
                              回复
                            </EdButton>
                          </div>
                          {canDeleteComment(c) && (
                            <EdButton size="sm" variant="danger" onClick={() => deleteComment(c)}>
                              删除
                            </EdButton>
                          )}
                        </div>

                        {(subs.length > 0 || remainingSubs > 0) && (
                          <div className="ed-article-subcomments">
                            {subs.map((sub) => (
                              <div key={sub.commentId} className="ed-article-subcomment">
                                <div className="ed-article-comment__head">
                                  <div className="ed-article-author">
                                    {sub.authorAvatar && (
                                      <img src={sub.authorAvatar} alt="" className="ed-article-author__avatar" loading="lazy" />
                                    )}
                                    <span className="ed-article-author__name">{sub.authorName || sub.uid.slice(0, 8)}</span>
                                    {sub.isOwn && <span className="ed-tag ed-tag--ok">Bot</span>}
                                    {sub.isArticleAuthor && <span className="ed-tag ed-tag--gold">作者</span>}
                                    {sub.replyToName && (
                                      <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>回复 @{sub.replyToName}</span>
                                    )}
                                  </div>
                                  <span style={{ fontSize: 11.5, color: "var(--ink-faint)" }}>
                                    {formatTime(sub.createdAt)}
                                  </span>
                                </div>

                                {sub.content && <p className="ed-article-comment__text">{sub.content}</p>}

                                {sub.imageList && sub.imageList.length > 0 && (
                                  <div className="ed-article-media-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(90px, 1fr))" }}>
                                    {sub.imageList.map((img, idx) =>
                                      img.url ? (
                                        <a
                                          key={`${img.url}-${idx}`}
                                          href={img.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="ed-article-media-item"
                                        >
                                          <img src={img.url} alt={`回复配图 ${idx + 1}`} loading="lazy" />
                                        </a>
                                      ) : null
                                    )}
                                  </div>
                                )}

                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                                  <div style={{ display: "flex", gap: 6 }}>
                                    <EdButton
                                      size="sm"
                                      variant={sub.liked ? "primary" : "ghost"}
                                      onClick={() => toggleLikeComment(sub)}
                                    >
                                      <Heart size={11} fill={sub.liked ? "currentColor" : "none"} style={{ marginInlineEnd: 4 }} />
                                      {sub.likeCount}
                                    </EdButton>
                                    <EdButton
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => setReplyTarget({ ...sub, parentId: sub.parentId || c.commentId })}
                                    >
                                      回复
                                    </EdButton>
                                  </div>
                                  {canDeleteComment(sub) && (
                                    <EdButton size="sm" variant="danger" onClick={() => deleteComment(sub)}>
                                      删除
                                    </EdButton>
                                  )}
                                </div>
                              </div>
                            ))}

                            {remainingSubs > 0 && (
                              <div>
                                <EdButton
                                  size="sm"
                                  variant="ghost"
                                  disabled={!!loadingRepliesFor[c.commentId]}
                                  onClick={() => loadMoreReplies(c)}
                                >
                                  {loadingRepliesFor[c.commentId] ? "加载中..." : `展开其余 ${remainingSubs} 条回复`}
                                </EdButton>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}

                {commentHasMore && (
                  <div style={{ display: "flex", justifyContent: "center", paddingTop: 4 }}>
                    <EdButton
                      size="sm"
                      variant="ghost"
                      disabled={commentsLoading}
                      onClick={() =>
                        loadComments(currentArea, currentChannel, detailArticle.articleId, {
                          append: true,
                          cursor: commentNextCursor,
                        })
                      }
                    >
                      加载更多评论
                    </EdButton>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </SlideSheet>

      {/* Create / Edit Article Sheet */}
      <SlideSheet
        open={!!editor}
        wide
        title={editor?.mode === "edit" ? "编辑帖子" : "发布新帖子"}
        onClose={() => setEditor(null)}
        footer={
          editor && (
            <>
              <EdButton variant="ghost" onClick={() => setEditor(null)}>取消</EdButton>
              <EdButton type="submit" form="article-editor-form" variant="primary" disabled={submittingEditor}>
                {submittingEditor ? "提交中..." : editor.mode === "edit" ? "保存修改" : "立即发布"}
              </EdButton>
            </>
          )
        }
      >
        {editor && (
          <form id="article-editor-form" onSubmit={submitEditor} style={{ display: "grid", gap: 16 }}>
            <div className="ed-field">
              <label htmlFor={titleId} className="ed-field__label">
                帖子标题 <span aria-hidden="true">*</span>
              </label>
              <input
                id={titleId}
                name="title"
                className="ed-input"
                required
                value={editor.title}
                placeholder="输入帖子标题"
                onChange={(e) => setEditor({ ...editor, title: e.target.value })}
              />
            </div>

            <div className="ed-form-grid">
              <div className="ed-field">
                <label className="ed-field__label">所属分区</label>
                <EditorialSelect
                  value={editor.sectionId}
                  onChange={(v) => setEditor({ ...editor, sectionId: v })}
                  options={sectionOptions}
                />
              </div>
              <div className="ed-switch-row" style={{ alignSelf: "end", height: 40 }}>
                <span className="ed-field__label">详情页显示封面</span>
                <ToggleSwitch
                  checked={editor.showCover}
                  onChange={(v) => setEditor({ ...editor, showCover: v })}
                  ariaLabel="详情页显示封面"
                />
              </div>
            </div>

            <div className="ed-field">
              <label htmlFor={contentId} className="ed-field__label">正文内容</label>
              <textarea
                id={contentId}
                name="content"
                className="ed-input ed-article-textarea"
                value={editor.content}
                placeholder="输入帖子正文..."
                onChange={(e) => setEditor({ ...editor, content: e.target.value })}
              />
            </div>

            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span className="ed-field__label">配图附件（{editor.attachments.length}）</span>
                <label className="ed-article-upload-label">
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    className="ed-visually-hidden"
                    disabled={uploadingEditorImg}
                    onChange={(e) => {
                      const files = e.currentTarget.files;
                      void uploadImages(
                        files,
                        (items) =>
                          setEditor((prev) =>
                            prev ? { ...prev, attachments: [...prev.attachments, ...items] } : prev
                          ),
                        setUploadingEditorImg
                      );
                      e.currentTarget.value = "";
                    }}
                  />
                  <ImagePlus size={14} aria-hidden="true" />
                  <span>{uploadingEditorImg ? "上传中..." : "上传图片"}</span>
                </label>
              </div>

              {editor.attachments.length > 0 && (
                <div className="ed-article-media-grid">
                  {editor.attachments.map((att, idx) => {
                    const video = isVideoAttachment(att);
                    const previewImg = resolvePreviewImage(att);
                    const mediaSrc = resolveMediaSrc(att);
                    const isCover = editor.coverIndex === idx;
                    return (
                      <div key={`${att.resource}-${idx}`} className="ed-article-media-item">
                        {previewImg ? (
                          <img src={previewImg} alt={video ? `视频封面 ${idx + 1}` : `附件 ${idx + 1}`} />
                        ) : video && mediaSrc ? (
                          <video muted playsInline preload="metadata" src={mediaSrc} />
                        ) : (
                          <div className="ed-empty" style={{ padding: 12, fontSize: 11 }}>
                            {video ? "视频附件" : att.resource.split("/").pop()}
                          </div>
                        )}
                        <div className="ed-article-media-item__bar">
                          <div style={{ display: "flex", gap: 4 }}>
                            {video && <span className="ed-tag ed-tag--ok">视频</span>}
                            <button
                              type="button"
                              className={`ed-tag ${isCover ? "ed-tag--gold" : "ed-tag--muted"}`}
                              style={{ border: "none", cursor: "pointer" }}
                              onClick={() => setEditor({ ...editor, coverIndex: idx })}
                            >
                              {isCover ? "封面" : "设为封面"}
                            </button>
                          </div>
                          <button
                            type="button"
                            className="ed-sheet__close"
                            style={{ width: 22, height: 22 }}
                            onClick={() => {
                              const next = editor.attachments.filter((_, i) => i !== idx);
                              const nextCover =
                                idx < editor.coverIndex
                                  ? editor.coverIndex - 1
                                  : Math.min(editor.coverIndex, Math.max(0, next.length - 1));
                              setEditor({ ...editor, attachments: next, coverIndex: nextCover });
                            }}
                            aria-label="移除附件"
                          >
                            <X size={11} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </form>
        )}
      </SlideSheet>

      {/* Section Management Sheet */}
      <SlideSheet
        open={sectionSheetOpen}
        title="分区管理"
        onClose={() => setSectionSheetOpen(false)}
      >
        <div style={{ display: "grid", gap: 16 }}>
          <form onSubmit={createSection} style={{ display: "flex", gap: 8 }}>
            <label htmlFor={newSectionId} className="ed-visually-hidden">
              新分区名称
            </label>
            <input
              id={newSectionId}
              className="ed-input"
              required
              value={newSectionName}
              placeholder="输入新分区名称..."
              onChange={(e) => setNewSectionName(e.target.value)}
            />
            <EdButton type="submit" variant="primary">新增</EdButton>
          </form>

          {sections.length === 0 ? (
            <div className="ed-empty">当前帖子频道暂无分区</div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {sections.map((sec) => (
                <div
                  key={sec.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: "1px solid var(--rule)",
                    background: "rgba(255, 255, 255, 0.025)",
                  }}
                >
                  <input
                    className="ed-input"
                    aria-label={`分区 ${sec.id} 名称`}
                    value={sectionDrafts[sec.id] ?? sec.name}
                    onChange={(e) => setSectionDrafts((prev) => ({ ...prev, [sec.id]: e.target.value }))}
                  />
                  <EdButton size="sm" variant="ghost" onClick={() => saveSectionName(sec)}>
                    保存
                  </EdButton>
                  <EdButton size="sm" variant="danger" onClick={() => deleteSection(sec)}>
                    删除
                  </EdButton>
                </div>
              ))}
            </div>
          )}
        </div>
      </SlideSheet>
    </div>
  );
}
