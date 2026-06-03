/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card, Input } from 'antd';
import { STATUS_MAP } from '../constants';

export default function CheckSheetTable({
  allProjectsData,
  getTotalRows,
  handleCellClick,
  handleRightClick,
  updateDailySummaryField
}) {
  // P1-6 修复：统一使用第一个项目的数据作为 daily summary 数据源
  // 注意：在多项目场景下，所有项目的整改/备注共用同一列（rowSpan），
  // 当前设计取第一个项目的数据，这可能需要在未来改为合并所有项目数据
  const firstProject = Object.values(allProjectsData)[0];
  const operator = firstProject?.dailySummary?.operator || '（待签字）';

  return (
    <Card title="日检查表录入" size="small">
      <div style={{ textAlign: 'right', marginBottom: 8 }}>
        <span>值班人员：{operator}</span>
      </div>

      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        border: '1px solid #d9d9d9',
        fontSize: '13px'
      }}>
        <thead>
          <tr style={{ backgroundColor: '#fafafa' }}>
            <th style={{
              border: '1px solid #d9d9d9',
              padding: '10px',
              fontWeight: 'bold',
              minWidth: '120px',
              textAlign: 'center',
              position: 'sticky',
              left: 0,
              backgroundColor: '#fafafa',
              zIndex: 10
            }}>项目名</th>
            <th style={{
              border: '1px solid #d9d9d9',
              padding: '10px',
              fontWeight: 'bold',
              minWidth: '300px',
              textAlign: 'center',
              position: 'sticky',
              left: '120px',
              backgroundColor: '#fafafa',
              zIndex: 10
            }}>现场巡视检查内容</th>
            <th style={{
              border: '1px solid #d9d9d9',
              padding: '10px',
              fontWeight: 'bold',
              width: '80px',
              textAlign: 'center'
            }}>状态</th>
            <th style={{
              border: '1px solid #d9d9d9',
              padding: '10px',
              fontWeight: 'bold',
              minWidth: '250px',
              textAlign: 'center'
            }}>发现问题及整改情况</th>
            <th style={{
              border: '1px solid #d9d9d9',
              padding: '10px',
              fontWeight: 'bold',
              minWidth: '200px',
              textAlign: 'center'
            }}>备注</th>
          </tr>
        </thead>
        <tbody>
          {(() => {
            const projectKeys = Object.keys(allProjectsData);
            let firstRowRendered = false;

            return projectKeys.map((project, projectIndex) => {
              const projectData = allProjectsData[project];

              return (
                <React.Fragment key={project}>
                  {projectData.template.check_items.map((item, itemIndex) => {
                    const key = `${itemIndex}`;
                    const cellData = projectData.checkData[key] || { status: 'UNCHECKED' };
                    const statusInfo = STATUS_MAP[cellData.status];
                    const isFirstRowInProject = itemIndex === 0;
                    const isFirstRowOverall = !firstRowRendered;

                    if (isFirstRowOverall) {
                      firstRowRendered = true;
                    }

                    return (
                      <tr key={`${project}_${itemIndex}`}>
                        {isFirstRowInProject && (
                          <td
                            style={{
                              border: '1px solid #d9d9d9',
                              padding: '10px',
                              fontWeight: 'bold',
                              verticalAlign: 'middle',
                              textAlign: 'center',
                              position: 'sticky',
                              left: 0,
                              backgroundColor: '#fff',
                              zIndex: 5
                            }}
                            rowSpan={projectData.template.check_items.length}
                          >
                            {project}
                          </td>
                        )}
                        <td style={{
                          border: '1px solid #d9d9d9',
                          padding: '10px',
                          position: 'sticky',
                          left: '120px',
                          backgroundColor: '#fff',
                          zIndex: 5
                        }}>{item}</td>
                        <td
                          style={{
                            border: '1px solid #d9d9d9',
                            padding: '10px',
                            textAlign: 'center',
                            backgroundColor: statusInfo.bgColor,
                            color: statusInfo.color,
                            cursor: 'pointer',
                            verticalAlign: 'middle'
                          }}
                          onClick={() => handleCellClick(project, itemIndex)}
                          onContextMenu={(e) => handleRightClick(project, itemIndex, e)}
                          title="左键切换正常/未检查，右键设置异常"
                        >
                          <span style={{ fontSize: '16px', fontWeight: 'bold' }}>{statusInfo.label}</span>
                        </td>
                        {isFirstRowOverall && (
                          <td
                            style={{
                              border: '1px solid #d9d9d9',
                              padding: '5px',
                              verticalAlign: 'middle'
                            }}
                            rowSpan={getTotalRows()}
                          >
                            <Input.TextArea
                              rows={3}
                              value={firstProject?.dailySummary?.rectification || ''}
                              onChange={(e) => updateDailySummaryField('rectification', e.target.value)}
                              placeholder="请输入发现问题及整改情况"
                              autoSize={{ minRows: 3, maxRows: 6 }}
                              style={{ fontSize: '13px', resize: 'none' }}
                            />
                          </td>
                        )}
                        {isFirstRowOverall && (
                          <td
                            style={{
                              border: '1px solid #d9d9d9',
                              padding: '5px',
                              verticalAlign: 'middle'
                            }}
                            rowSpan={getTotalRows()}
                          >
                            <Input.TextArea
                              rows={3}
                              value={firstProject?.dailySummary?.remark || ''}
                              onChange={(e) => updateDailySummaryField('remark', e.target.value)}
                              placeholder="请输入备注"
                              autoSize={{ minRows: 3, maxRows: 6 }}
                              style={{ fontSize: '13px', resize: 'none' }}
                            />
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </React.Fragment>
              );
            });
          })()}
        </tbody>
      </table>
    </Card>
  );
}
