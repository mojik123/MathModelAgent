<script setup lang="ts">
import {
	getAllFilesDownloadUrl,
	getFileDownloadUrl,
	getFiles,
} from "@/apis/filesApi";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
	SheetTrigger,
} from "@/components/ui/sheet";
import { useToast } from "@/components/ui/toast/use-toast";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import {
	Archive,
	ChevronDown,
	ChevronRight,
	Download,
	File,
	FileCode,
	FileImage,
	FileSpreadsheet,
	FileText,
	Files,
	Folder,
	FolderOpen,
	RefreshCw,
} from "lucide-vue-next";
import { computed, reactive, ref } from "vue";
import { useRoute } from "vue-router";

interface WorkspaceFile {
	filename?: string;
	name?: string;
	file_type?: string;
	type?: string;
	size?: number;
	modified_time?: string | number | Date;
}

// ---- 目录树类型 ----

interface TreeFile {
	/** 文件的完整相对路径（含子目录），用于下载 */
	relativePath: string;
	/** 仅文件名部分，用于显示 */
	baseName: string;
	/** 文件扩展名 */
	ext: string;
}

interface TreeDir {
	/** 子目录名，如 "5.1_问题1的模型建立与求解" */
	name: string;
	/** 论文编号前缀，如 "5.1" */
	sectionNum: string;
	/** 目录中文标签，如 "问题1的模型建立与求解" */
	label: string;
	files: TreeFile[];
}

interface FileTree {
	/** work_dir 根目录下的文件（非子目录） */
	rootFiles: TreeFile[];
	/** 按论文章节分组的子目录 */
	dirs: TreeDir[];
}

// ---- Reactive State ----

const route = useRoute();
const taskId = route.params.task_id;
const { toast } = useToast();

/** 文件列表弹窗显示状态 */
const fileListVisible = ref(false);

/** 文件列表数据 */
const fileList = ref<WorkspaceFile[]>([]);

/** 加载状态 */
const loadingFiles = ref(false);

/** 当前正在下载的文件名 */
const downloadingFile = ref<string | null>(null);

/** 是否正在下载全部文件 */
const downloadingAll = ref(false);

/**
 * 展开的子目录集合。
 * 使用 reactive(Set) 让 Vue 3 能追踪 add/delete 操作。
 */
const expandedDirs = reactive(new Set<string>());

// ---- Methods ----

/** 打开文件列表弹窗 */
const openFolder = async () => {
	try {
		loadingFiles.value = true;
		const res = await getFiles(taskId as string);

		if (res.data) {
			fileList.value = Array.isArray(res.data) ? res.data : [res.data];
			// 默认展开所有子目录
			expandedDirs.clear();
			for (const f of fileList.value) {
				const raw = (f.filename || f.name || "").replace(/\\/g, "/");
				const slashIdx = raw.indexOf("/");
				if (slashIdx !== -1) expandedDirs.add(raw.slice(0, slashIdx));
			}
			fileListVisible.value = true;
		} else {
			toast({
				title: "获取文件列表失败",
				description: "无法获取工作区文件列表",
				variant: "destructive",
			});
		}
	} catch (error) {
		console.error("获取文件列表失败:", error);
		toast({
			title: "错误",
			description: "获取文件列表时出现错误",
			variant: "destructive",
		});
	} finally {
		loadingFiles.value = false;
	}
};

// ---- 目录树计算 ----

/**
 * 将后端返回的平铺文件列表（含子目录相对路径）转换为目录树结构。
 * 后端 get_current_files() 使用 rglob 返回如 "5.1_问题1的模型建立与求解/fig1.png" 的路径。
 */
const fileTree = computed<FileTree>(() => {
	const rootFiles: TreeFile[] = [];
	const dirMap = new Map<string, TreeFile[]>();

	for (const f of fileList.value) {
		const raw = f.filename || f.name || "";
		if (!raw) continue;
		// 统一斜杠
		const normalized = raw.replace(/\\/g, "/");
		const slashIdx = normalized.indexOf("/");

		if (slashIdx === -1) {
			// 根目录文件
			rootFiles.push({
				relativePath: normalized,
				baseName: normalized,
				ext: normalized.split(".").pop()?.toLowerCase() ?? "",
			});
		} else {
			const dirName = normalized.slice(0, slashIdx);
			const baseName = normalized.slice(slashIdx + 1);
			if (!dirMap.has(dirName)) dirMap.set(dirName, []);
			dirMap.get(dirName)!.push({
				relativePath: normalized,
				baseName,
				ext: baseName.split(".").pop()?.toLowerCase() ?? "",
			});
		}
	}

	// 解析子目录名，提取论文编号和标签（如 "5.1_问题1的模型建立与求解" → "5.1" + "问题1的模型建立与求解"）
	const dirs: TreeDir[] = Array.from(dirMap.entries())
		.sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
		.map(([name, files]) => {
			const underscoreIdx = name.indexOf("_");
			const sectionNum = underscoreIdx !== -1 ? name.slice(0, underscoreIdx) : name;
			const label = underscoreIdx !== -1 ? name.slice(underscoreIdx + 1) : "";
			return { name, sectionNum, label, files };
		});

	return { rootFiles, dirs };
});

/** 切换子目录展开状态 */
function toggleDir(dirName: string) {
	if (expandedDirs.has(dirName)) {
		expandedDirs.delete(dirName);
	} else {
		expandedDirs.add(dirName);
	}
}

/** 根据文件名获取对应的图标组件 */
const getFileIcon = (fileName: string) => {
	const ext = fileName.split(".").pop()?.toLowerCase();
	if (["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"].includes(ext ?? "")) return FileImage;
	if (["py", "ipynb", "js", "ts", "json"].includes(ext ?? "")) return FileCode;
	if (["csv", "xlsx", "xls"].includes(ext ?? "")) return FileSpreadsheet;
	if (["txt", "md", "xml", "yml", "yaml"].includes(ext ?? "")) return FileText;
	return File;
};


/** 下载单个文件 */
const downloadSingleFile = async (filename: string) => {
	try {
		downloadingFile.value = filename;
		const res = await getFileDownloadUrl(taskId as string, filename);
		if (res.data?.download_url) {
			// 创建隐藏的链接元素并触发下载
			const link = document.createElement("a");
			link.href = res.data.download_url;
			link.download = filename;
			link.target = "_blank";
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);

			toast({
				title: "下载成功",
				description: `文件 ${filename} 开始下载`,
			});
		} else {
			throw new Error("获取下载链接失败");
		}
	} catch (error) {
		console.error("下载文件失败:", error);
		toast({
			title: "下载失败",
			description: `下载文件 ${filename} 时出现错误`,
			variant: "destructive",
		});
	} finally {
		downloadingFile.value = null;
	}
};

/** 下载所有文件（压缩包） */
const downloadAll = async () => {
	try {
		downloadingAll.value = true;
		const res = await getAllFilesDownloadUrl(taskId as string);
		if (res.data?.download_url) {
			// 创建隐藏的链接元素并触发下载
			const link = document.createElement("a");
			link.href = res.data.download_url;
			link.download = `task_${taskId}_files.zip`;
			link.target = "_blank";
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);

			toast({
				title: "下载成功",
				description: "所有文件压缩包开始下载",
			});
		} else {
			throw new Error("获取下载链接失败");
		}
	} catch (error) {
		console.error("下载所有文件失败:", error);
		toast({
			title: "下载失败",
			description: "下载所有文件时出现错误",
			variant: "destructive",
		});
	} finally {
		downloadingAll.value = false;
	}
};
</script>

<template>
  <Sheet v-model:open="fileListVisible">
    <SheetTrigger asChild>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button @click="openFolder()" :disabled="loadingFiles" class="flex gap-2" size="icon">
              <RefreshCw v-if="loadingFiles" class="w-4 h-4 animate-spin" />
              <Files v-else class="w-4 h-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>工作区文件</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

    </SheetTrigger>
    <SheetContent side="right" class="w-[400px] sm:w-[540px]">
      <SheetHeader>
        <SheetTitle class="flex items-center justify-between mr-5">
          <span>工作区文件</span>
          <Button
            size="sm"
            variant="outline"
            :disabled="downloadingAll"
            @click="downloadAll"
          >
            <RefreshCw v-if="downloadingAll" class="mr-1 h-4 w-4 animate-spin" />
            <Archive v-else class="mr-1 h-4 w-4" />
            全部下载
          </Button>
        </SheetTitle>
        <SheetDescription>
          运行的结果和产生在<span class="font-mono">backend/project/work_dir/{{ taskId }}/*</span> 目录下
        </SheetDescription>
      </SheetHeader>

      <div class="mt-6">
        <ScrollArea class="h-[calc(100vh-120px)]">
          <div v-if="fileList.length === 0" class="text-center py-8 text-gray-500">
            暂无文件
          </div>
          <div v-else class="space-y-1 pr-1">

            <!-- ── 子目录（按论文章节分组） ── -->
            <div
              v-for="dir in fileTree.dirs"
              :key="dir.name"
              class="rounded-lg border border-gray-200 overflow-hidden"
            >
              <!-- 目录头 -->
              <button
                class="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left select-none"
                @click="toggleDir(dir.name)"
              >
                <component
                  :is="expandedDirs.has(dir.name) ? ChevronDown : ChevronRight"
                  class="w-3.5 h-3.5 text-gray-400 flex-shrink-0"
                />
                <component
                  :is="expandedDirs.has(dir.name) ? FolderOpen : Folder"
                  class="w-4 h-4 text-amber-500 flex-shrink-0"
                />
                <span class="text-xs font-semibold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded flex-shrink-0">
                  {{ dir.sectionNum }}
                </span>
                <span class="text-sm font-medium text-gray-700 truncate">{{ dir.label }}</span>
                <span class="ml-auto text-xs text-gray-400 flex-shrink-0">{{ dir.files.length }} 个文件</span>
              </button>

              <!-- 目录内文件列表 -->
              <div v-if="expandedDirs.has(dir.name)" class="divide-y divide-gray-100">
                <div
                  v-for="file in dir.files"
                  :key="file.relativePath"
                  class="flex items-center gap-2.5 px-4 py-2 hover:bg-gray-50 transition-colors"
                >
                  <component :is="getFileIcon(file.baseName)" class="w-4 h-4 text-gray-500 flex-shrink-0" />
                  <span class="flex-1 text-sm text-gray-800 truncate min-w-0">{{ file.baseName }}</span>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <Button
                          @click="downloadSingleFile(file.relativePath)"
                          :disabled="downloadingFile === file.relativePath"
                          size="sm"
                          variant="ghost"
                          class="h-7 w-7 p-0 flex-shrink-0"
                        >
                          <RefreshCw v-if="downloadingFile === file.relativePath" class="w-3.5 h-3.5 animate-spin" />
                          <Download v-else class="w-3.5 h-3.5" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent><p>下载</p></TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>
            </div>

            <!-- ── 根目录文件（不属于任何章节子目录） ── -->
            <template v-if="fileTree.rootFiles.length > 0">
              <div class="mt-2 mb-1 px-1">
                <span class="text-xs font-medium text-gray-400 uppercase tracking-wide">根目录文件</span>
              </div>
              <div
                v-for="file in fileTree.rootFiles"
                :key="file.relativePath"
                class="flex items-center gap-3 p-2.5 rounded-lg border hover:bg-gray-50 transition-colors"
              >
                <component :is="getFileIcon(file.baseName)" class="w-4 h-4 text-gray-600 flex-shrink-0" />
                <span class="flex-1 text-sm text-gray-800 truncate min-w-0">{{ file.baseName }}</span>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <Button
                        @click="downloadSingleFile(file.relativePath)"
                        :disabled="downloadingFile === file.relativePath"
                        size="sm"
                        variant="ghost"
                        class="h-7 w-7 p-0 flex-shrink-0"
                      >
                        <RefreshCw v-if="downloadingFile === file.relativePath" class="w-3.5 h-3.5 animate-spin" />
                        <Download v-else class="w-3.5 h-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent><p>下载</p></TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </template>

          </div>
        </ScrollArea>
      </div>

    </SheetContent>
  </Sheet>
</template>
