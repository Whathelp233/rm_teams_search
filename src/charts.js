import { init, use } from 'echarts/core'
import { BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, RadarChart, GridComponent, RadarComponent, TooltipComponent, CanvasRenderer])

export { init }
