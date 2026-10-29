/***********************************************************************************************************************************
 ** 【文件名称】  lcd_st7735.c
 ** 【编写人员】  魔女开发板团队
 ** 【淘    宝】  魔女开发板      https://demoboard.taobao.com
 ***********************************************************************************************************************************
 ** 【文件功能】  
 **
 ** 【适用平台】  
 **
 ** 【本地函数】
 **
 ** 【更新记录】
 **               
************************************************************************************************************************************/
#include "bsp_LCD_ST7735.h"
#include "font.h" 




/*****************************************************************************
 ** 本地变量
 *****************************************************************************/
struct _LCD              // 结构体：用于保存信息、状态
{
    u8  InitOK;
    uint16_t width;           // LCD 宽度
    uint16_t height;          // LCD 高度

    uint32_t bColor;          // 背景色
} xLCD;



/*****************************************************************************
 ** 本地函数
 ****************************************************************************/
static void gpioInit(void);                                         // 引脚初始化
static void spiInit(void);                                          // SPI通信协议初始化
static void sendOrder(uint16_t order);                              // 向液晶屏发送：寄存器地址值(指令), 8位
static void sendByte(u8  Data);                                     // 向液晶屏发送：数据，8位
static void sendShort(uint16_t Data);                               // 向液晶屏发送：数据，16位
static void setCursor(uint16_t xStart, uint16_t yStart, uint16_t xEnd, uint16_t yEnd);  // 设置显示区域





/*****************************************************************************
 ** 显示屏控制宏定义, 主要为了简化文件内操作
 *****************************************************************************/
// LCD_CS
#define    LCD_CS_LOW      (LCD_CS_GPIO->BSRR = (uint32_t)LCD_CS_PIN << 16)
#define    LCD_CS_HIGH     (LCD_CS_GPIO->BSRR = LCD_CS_PIN)
//
#define    LCD_BLK_LOW     (LCD_BLK_GPIO->BSRR = (uint32_t)LCD_BLK_PIN << 16)
#define    LCD_BLK_HIGH    (LCD_BLK_GPIO->BSRR = LCD_BLK_PIN)

#define    LCD_RS_LOW      (LCD_DC_GPIO->BSRR = (uint32_t)LCD_DC_PIN << 16)
#define    LCD_RS_HIGH     (LCD_DC_GPIO->BSRR = LCD_DC_PIN)




/******************************************************************************
 * 函  数： delay_ms
 * 功  能： ms 延时函数
 * 备  注： 1、系统时钟168MHz
 *          2、打勾：Options/ c++ / One ELF Section per Function
            3、编译优化级别：Level 3(-O3)
 * 参  数： uint32_t  ms  毫秒值
 * 返回值： 无
 ******************************************************************************/
static volatile uint32_t ulTimesMS;    // 使用volatile声明，防止变量被编译器优化
static void delay_ms(uint16_t ms)
{
    ulTimesMS = ms * 16500;
    while (ulTimesMS)
        ulTimesMS--;                   // 操作外部变量，防止空循环被编译器优化掉
}



// SPI通信协议初始化
// 重要：因为SPI总线可能挂载多个要求不同通信参数的设备，最好在每次通信前，调用一次配置函数
static void spiInit(void)
{
    SPI_InitTypeDef  SPI_InitStructure;
         
    RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;                                 // SPI1时钟使能

    SPI_InitStructure.SPI_Direction = SPI_Direction_2Lines_FullDuplex;  // 设置SPI单向或者双向的数据模式:SPI设置为双线双向全双工  SPI_Direction_1Line_Tx
    SPI_InitStructure.SPI_Mode = SPI_Mode_Master;                       // 设置SPI工作模式:设置为主SPI
    SPI_InitStructure.SPI_DataSize = SPI_DataSize_8b;                   // 设置SPI的数据大小:SPI发送接收8位帧结构
    SPI_InitStructure.SPI_CPOL = SPI_CPOL_High;                         // 选择了串行时钟的稳态:时钟悬空高
    SPI_InitStructure.SPI_CPHA = SPI_CPHA_2Edge;                        // 数据捕获于第二个时钟沿
    SPI_InitStructure.SPI_NSS = SPI_NSS_Soft;                           // NSS信号由硬件（NSS管脚）还是软件（使用SSI位）管理:内部NSS信号有SSI位控制
    SPI_InitStructure.SPI_BaudRatePrescaler = SPI_BaudRatePrescaler_4;  // 定义波特率预分频的值:波特率预分频值为2
    SPI_InitStructure.SPI_FirstBit = SPI_FirstBit_MSB;                  // 指定数据传输从MSB位还是LSB位开始:数据传输从MSB位开始
    SPI_InitStructure.SPI_CRCPolynomial = 7;                            // CRC值计算的多项式
    SPI_Init(SPI1, &SPI_InitStructure);                                 // 根据SPI_InitStruct中指定的参数初始化外设SPIx寄存器

    SPI_Cmd(LCD_SPI_PORT, ENABLE);                                      // 使能SPI外设
}



// 引脚初始化
static void gpioInit(void)
{        
    GPIO_InitTypeDef GPIO_InitStructure;  
    
    // SCK 引脚时钟使能
    if(LCD_SCK_GPIO==GPIOA)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    if(LCD_SCK_GPIO==GPIOB)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
    if(LCD_SCK_GPIO==GPIOC)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN;
    if(LCD_SCK_GPIO==GPIOD)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIODEN;
    if(LCD_SCK_GPIO==GPIOE)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOEEN;
    if(LCD_SCK_GPIO==GPIOF)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOFEN;
    if(LCD_SCK_GPIO==GPIOG)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOGEN;
    // MOSI 引脚时钟使能
    if(LCD_MOSI_GPIO==GPIOA)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    if(LCD_MOSI_GPIO==GPIOB)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
    if(LCD_MOSI_GPIO==GPIOC)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN;
    if(LCD_MOSI_GPIO==GPIOD)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIODEN;
    if(LCD_MOSI_GPIO==GPIOE)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIOEEN;
    if(LCD_MOSI_GPIO==GPIOF)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIOFEN;
    if(LCD_MOSI_GPIO==GPIOG)   RCC->AHB1ENR |= RCC_AHB1ENR_GPIOGEN;
    // DC 引脚时钟使能
    if(LCD_DC_GPIO==GPIOA)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    if(LCD_DC_GPIO==GPIOB)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
    if(LCD_DC_GPIO==GPIOC)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN;
    if(LCD_DC_GPIO==GPIOD)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIODEN;
    if(LCD_DC_GPIO==GPIOE)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOEEN;
    if(LCD_DC_GPIO==GPIOF)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOFEN;
    if(LCD_DC_GPIO==GPIOG)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOGEN;
    // CS 引脚时钟使能        
    if(LCD_CS_GPIO==GPIOA)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    if(LCD_CS_GPIO==GPIOB)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
    if(LCD_CS_GPIO==GPIOC)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN;
    if(LCD_CS_GPIO==GPIOD)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIODEN;
    if(LCD_CS_GPIO==GPIOE)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOEEN;
    if(LCD_CS_GPIO==GPIOF)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOFEN;
    if(LCD_CS_GPIO==GPIOG)     RCC->AHB1ENR |= RCC_AHB1ENR_GPIOGEN;
    // BLK 引脚时钟使能
    if(LCD_BLK_GPIO==GPIOA)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    if(LCD_BLK_GPIO==GPIOB)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOBEN;
    if(LCD_BLK_GPIO==GPIOC)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOCEN;
    if(LCD_BLK_GPIO==GPIOD)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIODEN;
    if(LCD_BLK_GPIO==GPIOE)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOEEN;
    if(LCD_BLK_GPIO==GPIOF)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOFEN;
    if(LCD_BLK_GPIO==GPIOG)    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOGEN;
    
    // SCK 引脚工作模式
    GPIO_InitStructure.GPIO_Pin   = LCD_SCK_PIN;                        // 引脚编号
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_AF;                       // 引脚方向: 复用功能
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;                      // 输出模式：推挽
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_100MHz;                  // 输出最大速度
    GPIO_Init(LCD_SCK_GPIO, &GPIO_InitStructure);                       // 初始化：把上述参数，更新到芯片寄存器
    // 配置复用功能
    GPIO_PinAFConfig(LCD_SCK_GPIO, LCD_SCK_PIN_SOURCE, GPIO_AF_SPI1);   // 配置复用功能
    
    // MOSI 引脚工作模式
    GPIO_InitStructure.GPIO_Pin   = LCD_MOSI_PIN;                       // 引脚编号
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_AF;                       // 引脚方向: 复用功能
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;                      // 输出模式：推挽
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_100MHz;                  // 输出最大速度
    GPIO_Init(LCD_MOSI_GPIO, &GPIO_InitStructure);                      // 初始化：把上述参数，更新到芯片寄存器
    // 配置复用功能
    GPIO_PinAFConfig(LCD_MOSI_GPIO, LCD_MOSI_PIN_SOURCE, GPIO_AF_SPI1); // 配置复用功能
    
    // DC 引脚工作模式
    GPIO_InitStructure.GPIO_Pin   = LCD_DC_PIN;                         // 引脚编号
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_OUT;                      // 引脚方向: 复用功能
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;                      // 输出模式：推挽
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_100MHz;                  // 输出最大速度
    GPIO_Init(LCD_DC_GPIO, &GPIO_InitStructure);                        // 初始化：把上述参数，更新到芯片寄存器
  
    // CS 引脚工作模式
    GPIO_InitStructure.GPIO_Pin   = LCD_CS_PIN;                         // 引脚编号
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_OUT;                      // 引脚方向: 复用功能
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;                      // 输出模式：推挽
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_100MHz;                  // 输出最大速度
    GPIO_Init(LCD_CS_GPIO, &GPIO_InitStructure);                        // 初始化：把上述参数，更新到芯片寄存器  
    
    // BLK 引脚工作模式
    GPIO_InitStructure.GPIO_Pin   = LCD_BLK_PIN;                        // 引脚编号
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_OUT;                      // 引脚方向: 复用功能
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;                      // 输出模式：推挽
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_100MHz;                  // 输出最大速度
    GPIO_Init(LCD_BLK_GPIO, &GPIO_InitStructure);                       // 初始化：把上述参数，更新到芯片寄存器  
}



// SPI发送传送1字节
static u8 spiSendByte(u8 data)
{
    static uint16_t retry;
    retry = 0;
    while ((LCD_SPI_PORT -> SR & 2) == 0)  // 等待发送区为空
    {        
        retry++;
        if (retry > 500) return 0;
    }
    LCD_SPI_PORT ->DR = data;
    retry = 0;
    while ((LCD_SPI_PORT -> SR & 1) == 0)  // 等待接收完数据
    {        
        retry++;
        if (retry > 250) return 0;
    }
    return LCD_SPI_PORT -> DR ;
}



// 向LCD发送寄存器地址(指令)
static void sendOrder(uint16_t order)
{
    LCD_CS_LOW;            // SPI设备片选拉低，开始通信
    LCD_RS_LOW;            // RS高: 数据值， RS低: 寄存器地址值
    spiSendByte(order);    // 发送 寄存器地址值
    LCD_CS_HIGH;           // SPI设备片选拉高，结束通信
}

// 向LCD发送数值
static void sendByte(u8 data)
{
    LCD_CS_LOW;            // SPI设备片选拉低，开始通信
    LCD_RS_HIGH;           // RS高: 数据值， RS低: 寄存器地址值
    spiSendByte(data);     // 发送1字节
    LCD_CS_HIGH;           // SPI设备片选拉高，结束通信
}

// 向LCD发送2个字节
static void sendShort(uint16_t data)
{
    LCD_CS_LOW;            // SPI设备片选拉低，开始通信
    LCD_RS_HIGH;           // RS高: 数据， RS低: 指令
    spiSendByte(data >> 8);// 发送1字节
    spiSendByte(data);     // 发送1字节
    LCD_CS_HIGH;           // SPI设备片选拉高，结束通信
}

//写寄存器: 寄存器地址，数据
//static void sendRegisterValue(u8 reg, uint16_t val)
//{
//    sendOrder(reg);
//    sendShort(val);
//}

/*****************************************************************
 * 函  数：setCursor
 * 功  能：设置显示区域，在此区域写点数据自动换行
 * 参  数：xStart横坐标起点, yStart纵坐标起点
 *         xEnd横坐标线束点，yEnd纵坐标线束点
 * 返回值：无
******************************************************************/
static void setCursor(uint16_t xStart, uint16_t yStart, uint16_t xEnd, uint16_t yEnd)
{
    sendOrder(0x2A);
    sendByte(0x00);    // 起始位置x高位，因为1.8寸屏是128*160, 不大于255, 直接写0省事
    sendByte(xStart);  // 起始位置x低位，值传递时自动舍弃了高8位，也省得运算了
    sendByte(0x00);    // 起始位置y高位
    sendByte(xEnd);    // 起始位置x位位

    sendOrder(0x2B);
    sendByte(0x00);
    sendByte(yStart);
    sendByte(0x00);
    sendByte(yEnd);

    sendOrder(0x2c);  // 发送写数据命令
}

/*****************************************************************
 * 函  数：drawPoint
 * 功  能：画一个点
 * 参  数：x坐标，y坐标, 16位颜色值
 * 返回值：无
 *
 * 备  注：淘宝 https://demoboard.taobao.com
 * 分  享：最后修改_2020年09月01日
******************************************************************/
static void drawPoint(uint16_t x, uint16_t y, uint16_t color)
{
    setCursor(x, y, x, y);      // 设置光标位置
    sendShort(color);
}

/******************************************************************
 * 函数名： LCD_Fill
 * 功  能： 在指定区域内填充单个颜色
 *          屏幕坐标从1开始；屏幕左右和下方实际上有多余行列
 * 参  数： uint16_t xStart, yStart  左上角起始坐标
 *          uint16_t xEnd,   yEnd    右下角起始坐标
 *          uint32_t Color           填充的颜色
 *
 * 备  注： 淘宝 https://demoboard.taobao.com
 * 分  享： 最后修改_2020年09月01日
 *****************************************************************/
void LCD_Fill(uint16_t xStart, uint16_t yStart, uint16_t xEnd, uint16_t yEnd, uint16_t color)
{
    spiInit();                                      // 防止SPI参数被其它设备修改了
    uint32_t pixel = (xEnd - xStart + 1) * (yEnd - yStart + 1); // 填充的像素数量

    setCursor(xStart, yStart, xEnd, yEnd);          // 设定填充范围
    while (pixel-- > 0)                             // 发送颜色值
        sendShort(color);
}

/******************************************************************
 * 函数名： LCD_Line
 * 功  能： 画线
 * 参  数： uint16_t x1,y1  起点坐标
 *          uint16_t x2,y2  终点坐标
 *          uint32_t Color  颜色
 *****************************************************************/
void LCD_Line(uint16_t sX, uint16_t sY, uint16_t eX, uint16_t eY, uint16_t color)
{
    spiInit();                                      // 防止SPI参数被其它设备修改了

    uint16_t t;
    int xerr = 0, yerr = 0, delta_x, delta_y, distance;
    int incx, incy, uRow, uCol;
    delta_x = eX - sX; //计算坐标增量
    delta_y = eY - sY;
    uRow = sX;
    uCol = sY;
    if (delta_x > 0)incx = 1; //设置单步方向
    else if (delta_x == 0)incx = 0; //垂直线
    else
    {
        incx = -1;
        delta_x = -delta_x;
    }
    if (delta_y > 0)incy = 1;
    else if (delta_y == 0)incy = 0; //水平线
    else
    {
        incy = -1;
        delta_y = -delta_y;
    }
    if (delta_x > delta_y)distance = delta_x;  // 选取基本增量坐标轴
    else distance = delta_y;
    for (t = 0; t <= distance + 1; t++)        // 画线输出
    {
        drawPoint(uRow, uCol, color);          // 画点
        xerr += delta_x ;
        yerr += delta_y ;
        if (xerr > distance)
        {
            xerr -= distance;
            uRow += incx;
        }
        if (yerr > distance)
        {
            yerr -= distance;
            uCol += incy;
        }
    }
}



/******************************************************************
 * 函数名： LCD_Circle
 * 功  能： 在指定位置画圆
 * 参  数： uint16_t Xpos     X坐标
 *          uint16_t Ypos     起点Y坐标
 *          uint16_t Radius   半径
 *          uint16_t _color   颜色
 * 备  注： 
 *****************************************************************/
void LCD_Circle(uint16_t Xpos, uint16_t Ypos, uint16_t Radius, uint16_t _color)
{
    int16_t mx = Xpos, my = Ypos, x = 0, y = Radius;
    int16_t d = 1 - Radius;
    while (y > x)
    {
        drawPoint(x + mx, y + my, _color);
        drawPoint(-x + mx, y + my, _color);
        drawPoint(-x + mx, -y + my, _color);
        drawPoint(x + mx, -y + my, _color);
        drawPoint(y + mx, x + my, _color);
        drawPoint(-y + mx, x + my, _color);
        drawPoint(y + mx, -x + my, _color);
        drawPoint(-y + mx, -x + my, _color);
        if (d < 0)
        {
            d += 2 * x + 3;
        }
        else
        {
            d += 2 * (x - y) + 5;
            y--;
        }
        x++;
    }
}

/******************************************************************
 * 函数名： LCD_Image
 * 功  能： 在指定区域内填充指定图片数据
 *          图片数据在font.h文件中.只适合少量图片保存
 *          Image2Lcd转换：水平扫描，16位真彩色
 * 参  数： uint16_t x,y     左上角起始坐标
 *          uint16_t width   图片宽度
 *          uint16_t height  图片高度
 *          u8* image   数据缓存地址
 * 备  注： 最后修改_2020年09月2日
 *****************************************************************/
void LCD_Image(uint16_t x, uint16_t y, uint16_t width, uint16_t height, const u8 *image)
{
    spiInit();                                      // 防止SPI参数被其它设备修改了

    uint16_t colorData = 0;
    uint32_t cnt = 0;

    for (uint16_t i = 0; i < height; i++)           // 一行一行地显示
    {
        setCursor(x, y + i, x + width, y + height); // 重新设置光标位置
        for (uint16_t j = 0; j < width; j++)        // 一行中，从左到事，逐个像素处理
        {
            colorData = (image[cnt * 2 + 1] << 8) | image[cnt * 2];
            sendShort(colorData);                   // 写入16位颜色数据
            cnt++;
        }
    }
}



/******************************************************************
 * 函数名： drawAscii
 * 功  能： 在指定位置显示一个字符
 * 参  数： uint16_t x,y     起始坐标
 *          u8  num     要显示的字符:" "--->"~"
 *          u8  size    字体大小 12/16/24/32
 *          uint32_t bColor  字体背景颜色
 *          uint32_t fColor  字体颜色
 * 备  注： 参考原子哥和野火大神的代码后修改  资料存放Q群： 
 *****************************************************************/
static void drawAscii(uint16_t x, uint16_t y, u8 num, u8 size, uint32_t bColor, uint32_t fColor)
{
    spiInit();                                                  // 防止SPI参数被其它设备修改了

    if (xLCD.InitOK == 0) return;

    u8 temp;
    uint16_t y0 = y;

    u8 csize = (size / 8 + ((size % 8) ? 1 : 0)) * (size / 2);  // 得到字体一个字符对应点阵集所占的字节数
    num = num - ' ';                                            // 得到偏移后的值（ASCII字库是从空格开始取模，所以-' '就是对应字符的字库）
    for (u8 t = 0; t < csize; t++)
    {
        if (size == 12)         temp = aFontASCII12[num][t];    // 调用1206字体
        else if (size == 16)    temp = aFontASCII16[num][t];    // 调用1608字体
        else if (size == 24)    temp = aFontASCII24[num][t];    // 调用2412字体
        else if (size == 32)    temp = aFontASCII32[num][t];    // 调用3216字体
        else return;                                            // 没有的字库
                                                                
        for (u8 t1 = 0; t1 < 8; t1++)                           
        {                                                       
            if (temp & 0x80)   drawPoint(x, y, fColor);         // 字体 画点
            else            drawPoint(x, y, bColor);            // 背景 画点
            temp <<= 1;                                         
            y++;                                                
            if (y >= xLCD.height)    return;                    // 超出屏幕高度(底)
            if ((y - y0) == size)                               
            {                                                   
                y = y0;                                         
                x++;                                            
                if (x >= xLCD.width) return;                    // 超出屏幕宽度(宽)
                break;
            }
        }
    }
}



// 显示汉字
static void drawGBK(uint16_t x, uint16_t y, uint8_t *font, uint8_t size, uint16_t bColor, uint16_t fColor)
{
    u8 temp;
    uint16_t y0 = y;
    u8 GBK[128];
    u8 csize = (size / 8 + ((size % 8) ? 1 : 0)) * (size); // 得到字体一个字符对应点阵集所占的字节数

#ifdef GBK_STORAGE_ADDR                                    // 判断是否使用魔女科技的w25qxx.c文件, 防止编译错误; 可自行修改
    W25Q128_ReadFontData(font, size, GBK);                 // 得到相应大小的点阵数据
#endif

    spiInit();                                             // 防止SPI参数被其它设备修改了
    for (u8 t = 0; t < csize; t++)
    {
        temp = GBK[t];                                     // 得到GBK点阵数据
        for (u8 t1 = 0; t1 < 8; t1++)
        {
            if (temp & 0x80)   drawPoint(x, y, fColor);
            else            drawPoint(x, y, bColor);
            temp <<= 1;
            y++;
            if ((y - y0) == size)
            {
                y = y0;
                x++;
                break;
            }
        }
    }
}



/******************************************************************************
 * 函  数： LCD_String
 * 功  能： 在屏幕上显示字符串
 *          支持英文、中文
 *          符号、英文字模存放在font.h文件中，汉字字模存放在W25Q128中
 * 参  数： uint16_t  lcd_x   起始坐标X
 *          uint16_t  lcd_y   起始坐标y
 *          char*     pFont
 *          uint8_t   size    字体大小，12、16、24、32, 如果不是这4种规格，会默认使用24号字体
 *          uint32_t  bColor  字体背景颜色
 *          uint32_t  fColor  字体颜色
 * 返回值：
******************************************************************************/
void LCD_String(uint16_t lcd_x, uint16_t lcd_y, char *pFont, uint8_t size, uint16_t bColor, uint16_t fColor)
{
    if (xLCD .InitOK == 0) return;

    uint16_t xStart = lcd_x;

    if (size != 12 && size != 16 && size != 24 && size != 32)          // 字体大小控制
        size = 24;

    while (*pFont != 0)                                                // 连续读取字符串数据，直到'\0'时停止
    {                                                                  
        if (lcd_x > (xLCD.width - size))                               // 行位置判断，如果到了行末，就把光标换行
        {                                                              
            lcd_x = xStart;                                            
            lcd_y = lcd_y + size;                                      
        }                                                              
        if (lcd_y > (xLCD.height - size))                              // 列位置判断，如果到了列末，就返回，不再输出
            return;                                                    
                                                                       
        if (*pFont < 127)                                              // ASCII字符
        {
            drawAscii(lcd_x, lcd_y, *pFont, size, bColor, fColor);
            pFont++;
            lcd_x += size / 2;
        }
        else                                                           // 汉字显示
        {
#ifdef GBK_STORAGE_ADDR
            drawGBK(lcd_x, lcd_y, (u8 *)pFont, size, bColor, fColor);  // 判断是否使用魔女这样就不影响ASCII英文字符的输出
#endif

            pFont = pFont + 2;                                         // 下一个要显示的数据在内存中的位置
            lcd_x = lcd_x + size;                                      // 下一个要显示的数据在屏幕上的X位置
        }
    }
}



/******************************************************************
 * 函数名： LCD_ShowChinese
 * 功  能： 显示自行取模的汉字,
 *          字库数据在font文件中，只适合少量汉字固定输出
 *          PCtoLCD2018取模：阴码+列行式+逆向+C51格式
 * 参  数： uint16_t  x         坐标x
 *          uint16_t  y         坐标y
 *          uint8_t   index     字模数据在数组中的序号
 *          uint32_t  bColor    字体背景颜色
 *          uint32_t  fColor    字体颜色
 * 返  回:  无
 *****************************************************************/
void LCD_ShowChinese(uint8_t x, uint8_t y, uint8_t num, uint8_t size1, uint32_t bColor, uint32_t fColor)
{
    uint8_t m, temp;
    uint8_t x0 = x, y0 = y;
    uint16_t size3 = (size1 / 8 + ((size1 % 8) ? 1 : 0)) * size1; // 得到字体一个字符对应点阵集所占的字节数

    for (uint16_t i = 0; i < size3; i++)
    {
        if (size1 == 12)
        {
            temp = aFontChinese12[num][i];   // 调用12*12字体
        }
        else if (size1 == 16)
        {
            temp = aFontChinese16[num][i];   // 调用16*16字体
        }
        else if (size1 == 24)
        {
            temp = aFontChinese24[num][i];   // 调用24*24字体
        }
        else if (size1 == 32)
        {
            temp = aFontChinese32[num][i];   // 调用32*32字体
        }
        else
        {
            temp = aFontChinese12[num][i];   // 如果是非法字形，则调用12*12字体
        }
        for (m = 0; m < 8; m++)
        {
            if (temp & 0x01)
                drawPoint(x, y, fColor);
            else
                drawPoint(x, y,  bColor);
            temp >>= 1;
            y++;
        }
        x++;
        if ((x - x0) == size1)
        {
            x = x0;
            y0 = y0 + 8;
        }
        y = y0;
    }
}



/*****************************************************************
 * 函  数：LCD_Display
 * 功  能：显示屏开关
 * 参  数：0:熄，非0：开
 * 返回值：无
 * 备  注：淘宝 https://demoboard.taobao.com
******************************************************************/
void LCD_Display(uint8_t sw)
{
    if (sw == 0)
        LCD_BLK_LOW ;
    else
        LCD_BLK_HIGH ;
}



/*****************************************************************************
*函  数：LCD_Init
*功  能：初始化lcd
*参  数：为了简化理解、便于移植，参数(屏幕像素、显示方向)在h文件里进行修改
*返回值：无
*备  注：淘宝 https://demoboard.taobao.com
*****************************************************************************/
void LCD_Init(void)
{
    xLCD.InitOK = 0;
    xLCD.bColor  = BLACK;
    
    if ((LCD_DIR == 1) || (LCD_DIR == 3))  // 显示方向像素匹配
    {
        xLCD.width  = LCD_WIDTH ;          // 屏宽度像素，超过此值驱动芯片会自动换行，注意：如果屏幕右边有花屏，就加大这个值
        xLCD.height = LCD_HIGH ;           // 屏高度像素， 注意：如果屏幕下面有花屏，就加大这个值
    }
    else
    {
        xLCD.width  = LCD_HIGH;
        xLCD.height = LCD_WIDTH;
    }
    
    gpioInit();                            // 初始化GPIO    
    spiInit();                             // 初始化SPI外设、协议

    // 屏幕复位
#ifdef LCD_RST_GPIO
    LCD_RST_LOW ;           // LCD_RST=0   
    delay_ms(10);           // delay 20 ms
    LCD_RST_HIGH  ;         // LCD_RST=1
#endif
    delay_ms(200);          // delay 20 ms

    sendOrder(0x11);        // 退出睡眠模式
    delay_ms(120);          // Delay 120ms
    //------------------------------------ST7735S Frame Rate-----------------------------------------//
    sendOrder(0xB1);
    sendByte(0x05);
    sendByte(0x3C);
    sendByte(0x3C);

    sendOrder(0xB2);
    sendByte(0x05);
    sendByte(0x3C);
    sendByte(0x3C);

    sendOrder(0xB3);
    sendByte(0x05);
    sendByte(0x3C);
    sendByte(0x3C);
    sendByte(0x05);
    sendByte(0x3C);
    sendByte(0x3C);
    //------------------------------------End ST7735S Frame Rate-----------------------------------------//
    sendOrder(0xB4); // Dot inversion
    sendByte(0x03);

    sendOrder(0xC0); // ST7735R Power Sequence
    sendByte(0x28);
    sendByte(0x08);
    sendByte(0x04);

    sendOrder(0xC1);
    sendByte(0XC0);

    sendOrder(0xC2);
    sendByte(0x0D);
    sendByte(0x00);
    sendOrder(0xC3);

    sendByte(0x8D);
    sendByte(0x2A);

    sendOrder(0xC4);
    sendByte(0x8D);
    sendByte(0xEE);
    //---------------------------------End ST7735S Power Sequence-------------------------------------//
    sendOrder(0xC5);  // VCOM
    sendByte(0x1A);
    sendOrder(0x36);  // MX, MY, RGB mode
    if (LCD_DIR == 1)  sendByte(0xC0); // 重要：显示方向控制，C0/00/A0/60,  C8/08/A8/68
    if (LCD_DIR == 2)  sendByte(0x00);
    if (LCD_DIR == 3)  sendByte(0xA0);
    if (LCD_DIR == 4)  sendByte(0x60);
    //------------------------------------ST7735S Gamma Sequence-----------------------------------------//
    sendOrder(0xE0);
    sendByte(0x04);
    sendByte(0x22);
    sendByte(0x07);
    sendByte(0x0A);
    sendByte(0x2E);
    sendByte(0x30);
    sendByte(0x25);
    sendByte(0x2A);
    sendByte(0x28);
    sendByte(0x26);
    sendByte(0x2E);
    sendByte(0x3A);
    sendByte(0x00);
    sendByte(0x01);
    sendByte(0x03);
    sendByte(0x13);

    sendOrder(0xE1);
    sendByte(0x04);
    sendByte(0x16);
    sendByte(0x06);
    sendByte(0x0D);
    sendByte(0x2D);
    sendByte(0x26);
    sendByte(0x23);
    sendByte(0x27);
    sendByte(0x27);
    sendByte(0x25);
    sendByte(0x2D);
    sendByte(0x3B);
    sendByte(0x00);
    sendByte(0x01);
    sendByte(0x04);
    sendByte(0x13);
    // 后期复制增加的
    sendOrder(0x2a);
    sendByte(0x00);
    sendByte(0x00);
    sendByte(0x00);
    sendByte(0x7f);
    // 后期复制增加的
    sendOrder(0x2b);
    sendByte(0x00);
    sendByte(0x00);
    sendByte(0x00);
    sendByte(0x9f);

    sendOrder(0x3A); // 65k mode
    sendByte(0x05);

    sendOrder(0x29); // Display on

    LCD_BLK_HIGH ;
    LCD_Fill(1, 1, xLCD.width, xLCD.height, BLACK);
    xLCD.InitOK = 1;
}
