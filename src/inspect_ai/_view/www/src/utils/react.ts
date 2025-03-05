import { useEffect, useRef } from "react";

export const useWhyDidYouUpdate = (componentName: string, props: any) => {
  const previousProps = useRef(props);

  useEffect(() => {
    if (previousProps.current !== props) {
      const changedProps = Object.entries(props).reduce(
        (diff, [key, value]) => {
          if (previousProps.current[key] !== value) {
            diff[key] = {
              before: previousProps.current[key],
              after: value,
            };
          }
          return diff;
        },
        {} as Record<string, unknown>,
      );

      if (Object.keys(changedProps).length > 0) {
        console.log(`[${componentName}] props changed:`, changedProps);
      } else {
        console.log(`[${componentName}] no props changed`);
      }
    }

    previousProps.current = props;
  }, [props, componentName]);
};
